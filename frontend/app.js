/* ==========================================================================
   SpeakBuddy — frontend
   Talks only to POST /api/chat on this origin. No provider logic, no keys.
   ========================================================================== */

(function () {
  "use strict";

  // ── Tuning ───────────────────────────────────────────────────────────────

  var SILENCE_MS = 2100;        // pause that ends a turn
  var SPEECH_END_MS = 1300;     // wait once the engine reports speech stopped
  var TRAILING_GRACE_MS = 1600; // extra wait when the sentence sounds unfinished
  // One grace period only: 2100 + 1600 caps the wait at ~3.7s. Any new speech
  // resets the count, so a real pause-and-continue never gets cut off.
  var MAX_DEFERRALS = 1;
  var MIN_TURN_CHARS = 2;
  var MAX_HISTORY = 40;         // client-side cap; the server trims again

  // Recognition accent. The browser's default (usually en-US) mis-hears other
  // English varieties badly, so this is user-selectable and remembered.
  var LANG_KEY = "speakbuddy.lang";
  var DEFAULT_LANG = "en-IN";
  var LANGUAGES = [
    ["en-IN", "English (India)"],
    ["en-US", "English (US)"],
    ["en-GB", "English (UK)"],
    ["en-AU", "English (Australia)"],
    ["en-CA", "English (Canada)"],
    ["en-IE", "English (Ireland)"],
    ["en-NZ", "English (New Zealand)"],
    ["en-SG", "English (Singapore)"],
    ["en-PH", "English (Philippines)"],
    ["en-ZA", "English (South Africa)"]
  ];

  // A turn ending on one of these is almost certainly mid-thought, so give the
  // speaker more time instead of sending a fragment.
  var UNFINISHED_TAIL = new RegExp(
    "\\b(a|an|and|are|as|at|because|but|by|can|could|did|do|does|for|from|" +
    "had|has|have|how|i|if|in|is|it|its|like|my|of|on|or|our|should|so|that|" +
    "the|their|then|there|these|they|this|to|um|uh|er|very|was|we|were|what|" +
    "when|where|which|who|why|will|with|would|you|your)\\s*$", "i");

  var GREETING =
    "Hi! I'm SpeakBuddy. Tell me about your day, or anything on your mind — " +
    "just start talking whenever you're ready.";

  var MODE_NOTES = {
    casual: "Casual Chat — just conversation, no corrections.",
    lesson: "Lesson Mode — SpeakBuddy will gently correct you as you chat.",
    correction:
      "Speech Correction — every turn gets detailed feedback: what was wrong, " +
      "why, and how to improve."
  };

  // ── Elements ─────────────────────────────────────────────────────────────

  var el = {
    chat:        document.getElementById("chat"),
    statusPill:  document.getElementById("statusPill"),
    statusText:  document.getElementById("statusText"),
    micBtn:      document.getElementById("btnMic"),
    micLabel:    document.querySelector("#btnMic .mic-label"),
    interim:     document.getElementById("interim"),
    textForm:    document.getElementById("textForm"),
    textInput:   document.getElementById("textInput"),
    newBtn:      document.getElementById("btnNew"),
    modeBtns:    Array.prototype.slice.call(document.querySelectorAll(".mode-btn")),
    errorBanner: document.getElementById("errorBanner"),
    errorText:   document.getElementById("errorText"),
    errorRetry:  document.getElementById("errorRetry"),
    errorClose:  document.getElementById("errorClose"),
    accent:      document.getElementById("accentSelect"),
    voice:       document.getElementById("voiceSelect"),
    voicePicker: document.getElementById("voicePicker")
  };

  // ── State ────────────────────────────────────────────────────────────────

  var state = {
    mode: "correction",   // must match the .is-active button in index.html
    history: [],          // [{ role: "user"|"assistant", content: string }]
    status: "idle",       // idle | listening | thinking | speaking
    micOn: false,         // what the user asked for
    wantListening: false, // whether recognition should be running right now
    recognizing: false,   // whether recognition actually is running
    busy: false,          // a request is in flight
    buffer: "",           // finalised speech not yet sent
    interim: "",          // in-progress speech the engine hasn't finalised
    deferrals: 0,         // consecutive "sounds unfinished" grace periods
    lang: DEFAULT_LANG,
    serverSpeech: false,  // set from /api/config
    voiceAccent: "us",    // tutor voice, independent of what we listen for
    greeted: false
  };

  var VOICE_KEY = "speakbuddy.voiceAccent";
  var audioEl = null;   // <audio> used for server-generated speech

  var recognition = null;
  var silenceTimer = null;
  var speechWatchdog = null;
  var typingBubble = null;

  var SpeechRecognitionCtor =
    window.SpeechRecognition || window.webkitSpeechRecognition || null;
  var ttsSupported = "speechSynthesis" in window;
  var ttsVoice = null;

  // ── Status ───────────────────────────────────────────────────────────────

  var STATUS_LABEL = {
    idle: "Tap Start to begin",
    listening: "Listening",
    thinking: "Thinking",
    speaking: "Speaking"
  };

  function setStatus(next, labelOverride) {
    state.status = next;
    el.statusPill.className = "status-pill is-" + next;
    el.statusText.textContent = labelOverride || STATUS_LABEL[next];
  }

  function setStatusError(message) {
    el.statusPill.className = "status-pill is-error";
    el.statusText.textContent = message;
  }

  // ── Transcript rendering ─────────────────────────────────────────────────

  function nearBottom() {
    return el.chat.scrollHeight - el.chat.scrollTop - el.chat.clientHeight < 120;
  }

  function scrollToBottom(force) {
    if (force || nearBottom()) {
      el.chat.scrollTop = el.chat.scrollHeight;
    }
  }

  // Speech Correction replies come back as labelled lines. Highlight the
  // labels, building nodes rather than HTML so model output is never parsed
  // as markup.
  // Longer aliases come first only for readability; matching picks the longest
  // hit, so "Better way to say it:" wins over a bare "Better:". The short
  // forms stay listed so replies from an older prompt still render.
  var CORRECTION_LABELS = [
    "You said:",
    "Better way to say it:", "Better:",
    "Grammar improvements:", "Grammar:",
    "Word choice improvements:", "Word choice:",
    "Pronunciation:",
    "Why it matters:", "Why:",
    "Practice:",
    "Try a new conversation:", "Try:",
    "Great:", "Level up:"
  ];

  // Every line is spoken, in the order it appears — including "You said:", so
  // the learner hears their own sentence before the corrected one.
  var SPOKEN_LABELS = CORRECTION_LABELS;

  function looksLikeCorrection(text) {
    return /^\s*you said:/i.test(text);
  }

  function startsWith(line, label) {
    return line.toLowerCase().indexOf(label.toLowerCase()) === 0;
  }

  /** The subset of a correction reply that should be spoken aloud. */
  function speechTextFor(text) {
    if (!looksLikeCorrection(text)) return text;

    var spoken = [];
    text.split(/\r?\n/).forEach(function (raw) {
      var line = raw.trim();
      if (!line) return;

      for (var i = 0; i < SPOKEN_LABELS.length; i++) {
        if (startsWith(line, SPOKEN_LABELS[i])) { spoken.push(line); return; }
      }
    });

    // If the model ignored the shape, fall back to speaking the whole thing.
    // Newlines are kept so the audio splits on label boundaries.
    return spoken.length ? spoken.join("\n") : text;
  }

  function renderCorrection(node, text) {
    // Trim each line: models often leave trailing spaces, which `pre-wrap`
    // would otherwise render.
    var lines = text.split(/\r?\n/)
      .map(function (line) { return line.trim(); })
      .filter(function (line) { return line !== ""; });

    lines.forEach(function (line, index) {
      if (index > 0) node.appendChild(document.createTextNode("\n"));

      // Longest label first, so "Why it matters:" wins over "Why:".
      var label = null;
      var best = 0;
      for (var i = 0; i < CORRECTION_LABELS.length; i++) {
        var candidate = CORRECTION_LABELS[i];
        if (candidate.length > best && startsWith(line, candidate)) {
          label = line.slice(0, candidate.length);
          best = candidate.length;
        }
      }

      if (label) {
        var strong = document.createElement("strong");
        strong.className = "lbl";
        strong.textContent = label;
        node.appendChild(strong);
        node.appendChild(document.createTextNode(line.slice(label.length)));
      } else {
        node.appendChild(document.createTextNode(line));
      }
    });
  }

  function addBubble(role, text) {
    var stick = nearBottom();
    var node = document.createElement("div");
    node.className = "bubble " + role;

    if (role === "tutor" && looksLikeCorrection(text)) {
      node.className += " correction";
      renderCorrection(node, text);
    } else {
      node.textContent = text;
    }

    el.chat.appendChild(node);
    scrollToBottom(stick);
    return node;
  }

  function showTyping() {
    if (typingBubble) return;
    typingBubble = document.createElement("div");
    typingBubble.className = "bubble tutor typing";
    typingBubble.innerHTML = "<span></span><span></span><span></span>";
    el.chat.appendChild(typingBubble);
    scrollToBottom(true);
  }

  function hideTyping() {
    if (typingBubble && typingBubble.parentNode) {
      typingBubble.parentNode.removeChild(typingBubble);
    }
    typingBubble = null;
  }

  // ── Errors ───────────────────────────────────────────────────────────────

  var lastFailedRequest = null;

  function showError(message, retryable) {
    el.errorText.textContent = message;
    el.errorRetry.hidden = !retryable;
    el.errorBanner.hidden = false;
    scrollToBottom(true);
  }

  function clearError() {
    el.errorBanner.hidden = true;
    lastFailedRequest = null;
  }

  el.errorClose.addEventListener("click", clearError);
  el.errorRetry.addEventListener("click", function () {
    clearError();
    if (lastFailedRequest) requestReply();
  });

  // ── Speech recognition ───────────────────────────────────────────────────

  function buildRecognition() {
    var rec = new SpeechRecognitionCtor();
    rec.lang = state.lang;
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;

    rec.onstart = function () {
      state.recognizing = true;
      if (state.status !== "thinking" && state.status !== "speaking") {
        setStatus("listening");
      }
    };

    rec.onresult = function (event) {
      var interim = "";
      for (var i = event.resultIndex; i < event.results.length; i++) {
        var result = event.results[i];
        if (result.isFinal) {
          state.buffer += result[0].transcript + " ";
        } else {
          interim += result[0].transcript;
        }
      }
      // Kept so it can be rescued if the engine restarts mid-sentence.
      state.interim = interim;
      state.deferrals = 0;                 // they're talking again
      el.interim.textContent = interim || state.buffer.trim();
      scheduleCommit(SILENCE_MS);
    };

    // Fired when the engine stops detecting speech — usually beats the timer.
    rec.onspeechend = function () {
      if (spokenSoFar()) scheduleCommit(SPEECH_END_MS);
    };

    rec.onerror = function (event) {
      switch (event.error) {
        case "not-allowed":
        case "service-not-allowed":
          state.micOn = false;
          state.wantListening = false;
          syncMicButton();
          setStatusError("Microphone blocked");
          showError(
            "SpeakBuddy needs microphone access to hear you. Allow the microphone " +
            "in your browser's address bar, then press Start again. You can keep " +
            "practising by typing in the meantime.",
            false
          );
          break;

        case "no-speech":
        case "aborted":
          // Routine — onend restarts the engine.
          break;

        case "audio-capture":
          state.micOn = false;
          state.wantListening = false;
          syncMicButton();
          setStatusError("No microphone");
          showError(
            "No microphone was found. Connect one and press Start again.",
            false
          );
          break;

        case "network":
          showError(
            "Speech recognition lost its network connection. It will keep retrying.",
            false
          );
          break;

        default:
          break;
      }
    };

    rec.onend = function () {
      state.recognizing = false;

      // Chrome cycles the session every minute or so. Anything the engine had
      // not yet finalised would be thrown away, which is how whole chunks of a
      // sentence go missing — so promote it to the buffer before restarting.
      if (state.interim.trim()) {
        state.buffer += state.interim + " ";
        state.interim = "";
      }

      if (state.wantListening) {
        window.setTimeout(startRecognition, 250);
      }
    };

    return rec;
  }

  function startRecognition() {
    if (!recognition || state.recognizing || !state.wantListening) return;
    try {
      recognition.start();
    } catch (err) {
      // InvalidStateError just means it is already running.
    }
  }

  function stopRecognition() {
    state.wantListening = false;
    cancelCommit();
    if (recognition && state.recognizing) {
      try { recognition.stop(); } catch (err) { /* already stopped */ }
    }
    el.interim.textContent = "";
  }

  function resumeListening() {
    if (!state.micOn || !recognition) {
      if (state.status !== "idle") setStatus("idle", "Mic off");
      return;
    }
    state.wantListening = true;
    setStatus("listening");
    startRecognition();
  }

  // ── Turn detection ───────────────────────────────────────────────────────

  function scheduleCommit(delay) {
    cancelCommit();
    silenceTimer = window.setTimeout(commitTurn, delay);
  }

  function cancelCommit() {
    if (silenceTimer) {
      window.clearTimeout(silenceTimer);
      silenceTimer = null;
    }
  }

  /** Everything heard this turn, finalised or not. */
  function spokenSoFar() {
    return (state.buffer + " " + state.interim).replace(/\s+/g, " ").trim();
  }

  function commitTurn() {
    cancelCommit();

    var text = spokenSoFar();

    if (text.length < MIN_TURN_CHARS || state.busy) {
      state.buffer = "";
    state.interim = "";
      state.interim = "";
      el.interim.textContent = "";
      return;
    }

    // Ending on "and", "to", "because"… means they are mid-thought and just
    // pausing. Wait a little longer rather than sending half a sentence.
    if (UNFINISHED_TAIL.test(text) && state.deferrals < MAX_DEFERRALS) {
      state.deferrals++;
      scheduleCommit(TRAILING_GRACE_MS);
      return;
    }

    state.buffer = "";
    state.interim = "";
    state.interim = "";
    state.deferrals = 0;
    el.interim.textContent = "";
    sendTurn(text);
  }

  // ── Sending ──────────────────────────────────────────────────────────────

  function sendTurn(text) {
    clearError();
    state.history.push({ role: "user", content: text });
    trimHistory();
    addBubble("user", text);
    requestReply();
  }

  function trimHistory() {
    if (state.history.length > MAX_HISTORY) {
      state.history = state.history.slice(-MAX_HISTORY);
    }
  }

  function requestReply() {
    if (state.busy) return;

    state.busy = true;
    lastFailedRequest = null;
    stopRecognition();          // don't let the mic hear the tutor
    setStatus("thinking");
    showTyping();

    fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: state.history, mode: state.mode })
    })
      .then(function (response) {
        return response.json()
          .catch(function () { return {}; })
          .then(function (body) { return { ok: response.ok, body: body }; });
      })
      .then(function (result) {
        hideTyping();

        if (!result.ok) {
          var message = (result.body && result.body.error) ||
            "The tutor could not be reached. Please try again.";
          var retryable = !result.body || result.body.retryable !== false;
          lastFailedRequest = true;
          state.busy = false;
          setStatusError("Couldn't reply");
          showError(message, retryable);
          resumeListening();
          return;
        }

        var reply = (result.body && result.body.reply) || "";
        state.history.push({ role: "assistant", content: reply });
        trimHistory();
        addBubble("tutor", reply);
        state.busy = false;
        speak(speechTextFor(reply));
      })
      .catch(function () {
        hideTyping();
        state.busy = false;
        lastFailedRequest = true;
        setStatusError("Offline");
        showError(
          "Could not reach the SpeakBuddy server. Check that it is running, " +
          "then retry.",
          true
        );
        resumeListening();
      });
  }

  // ── Speech synthesis ─────────────────────────────────────────────────────

  function pickVoice() {
    if (!ttsSupported) return;
    var voices = window.speechSynthesis.getVoices();
    if (!voices.length) return;

    var wanted = state.lang.replace("_", "-").toLowerCase();

    // Prefer a voice in the chosen variety, then any English, then anything.
    var exact = voices.filter(function (v) {
      return (v.lang || "").replace("_", "-").toLowerCase() === wanted;
    });
    var english = voices.filter(function (v) { return /^en(-|_|$)/i.test(v.lang); });
    var pool = exact.length ? exact : (english.length ? english : voices);

    // Prefer a local (offline) voice — they start faster and don't cut out.
    ttsVoice = pool.filter(function (v) { return v.localService; })[0] || pool[0];
  }

  if (ttsSupported) {
    pickVoice();
    window.speechSynthesis.addEventListener("voiceschanged", pickVoice);
  }

  /**
   * Speak the tutor's reply. Server speech is preferred because browser voices
   * differ per device — many machines have no British or Indian English voice
   * at all — so the server keeps every device sounding the same. The browser
   * engine stays as an offline fallback.
   */
  function speak(text) {
    if (!text) {
      resumeListening();
      return;
    }
    if (state.serverSpeech) {
      speakViaServer(text);
      return;
    }
    speakViaBrowser(text);
  }

  var MAX_SEGMENT_CHARS = 240;   // keep each clip short so it arrives fast

  /**
   * Break a reply into short pieces, each synthesised as its own complete
   * clip. Short clips arrive quickly (low latency) and each one has a proper
   * length, so nothing gets cut off — a single long streamed clip lost its
   * final sentence because the browser could not tell where the audio ended.
   */
  function buildSegments(text) {
    var parts = text.split(/\r?\n/);

    // A single-paragraph reply (casual and lesson modes) splits on sentences.
    if (parts.length <= 1) {
      parts = text.match(/[^.!?]+[.!?]*/g) || [text];
    }

    var segments = [];
    var current = "";

    parts.forEach(function (raw) {
      var part = raw.trim();
      if (!part) return;

      if (current && current.length + part.length + 1 > MAX_SEGMENT_CHARS) {
        segments.push(current);
        current = part;
      } else {
        current = current ? current + " " + part : part;
      }
    });

    if (current) segments.push(current);
    return segments;
  }

  function speakUrl(text) {
    return "/api/speak?accent=" + encodeURIComponent(state.voiceAccent) +
           "&text=" + encodeURIComponent(text);
  }

  function speakViaServer(text) {
    stopAudio();
    setStatus("speaking");

    var segments = buildSegments(text);
    if (!segments.length) {
      resumeListening();
      return;
    }
    playSegment(segments, 0, null, text);
  }

  /**
   * Play segment `index`, having already started fetching it as `preloaded`,
   * and begin fetching the next one so playback runs without gaps.
   */
  function playSegment(segments, index, preloaded, fullText) {
    if (index >= segments.length) {
      audioEl = null;
      resumeListening();
      return;
    }

    var current = preloaded || new Audio(speakUrl(segments[index]));
    current.preload = "auto";
    audioEl = current;

    // Start the next clip downloading now, while this one plays.
    var next = null;
    if (index + 1 < segments.length) {
      next = new Audio(speakUrl(segments[index + 1]));
      next.preload = "auto";
      try { next.load(); } catch (err) { /* best effort */ }
    }

    var done = false;

    current.onended = function () {
      if (done) return;
      done = true;
      playSegment(segments, index + 1, next, fullText);
    };

    current.onerror = function () {
      if (done) return;
      done = true;
      audioEl = null;
      // Speak what is left with the browser rather than dropping it.
      speakViaBrowser(segments.slice(index).join(" "));
    };

    current.play().catch(function () {
      if (done) return;
      done = true;
      audioEl = null;
      resumeListening();   // autoplay blocked; don't strand the loop
    });
  }

  function stopAudio() {
    if (!audioEl) return;
    audioEl.onended = null;
    audioEl.onerror = null;
    try { audioEl.pause(); } catch (err) { /* already stopped */ }
    audioEl = null;
  }

  function speakViaBrowser(text) {
    if (!ttsSupported || !text) {
      resumeListening();
      return;
    }

    window.speechSynthesis.cancel();
    setStatus("speaking");

    var utterance = new SpeechSynthesisUtterance(text);
    if (ttsVoice) {
      utterance.voice = ttsVoice;
      utterance.lang = ttsVoice.lang;
    }
    utterance.rate = 0.98;
    utterance.pitch = 1.0;

    var done = false;
    function finish() {
      if (done) return;
      done = true;
      window.clearTimeout(speechWatchdog);
      resumeListening();
    }

    utterance.onend = finish;
    utterance.onerror = finish;

    // Some browsers drop onend silently; estimate ~2.5 words/second and add slack.
    var words = text.split(/\s+/).length;
    speechWatchdog = window.setTimeout(finish, (words / 2.5) * 1000 + 5000);

    window.speechSynthesis.speak(utterance);
  }

  function stopSpeaking() {
    stopAudio();
    if (ttsSupported) window.speechSynthesis.cancel();
    window.clearTimeout(speechWatchdog);
  }

  // ── Mic toggle ───────────────────────────────────────────────────────────

  function syncMicButton() {
    el.micBtn.setAttribute("aria-pressed", state.micOn ? "true" : "false");
    if (el.micLabel) el.micLabel.textContent = state.micOn ? "Stop" : "Start";
    el.micBtn.title = state.micOn ? "Turn microphone off" : "Turn microphone on";
  }

  function micOn() {
    if (!SpeechRecognitionCtor) return;

    state.micOn = true;
    syncMicButton();
    clearError();

    if (!recognition) recognition = buildRecognition();

    if (!state.greeted) {
      state.greeted = true;
      // The click is a user gesture, so speech synthesis is allowed to start.
      speak(GREETING);
      return;
    }
    resumeListening();
  }

  function micOff() {
    state.micOn = false;
    syncMicButton();
    stopSpeaking();
    stopRecognition();
    state.buffer = "";
    state.interim = "";
    setStatus("idle", "Mic off");
  }

  el.micBtn.addEventListener("click", function () {
    if (state.micOn) micOff(); else micOn();
  });

  // ── Mode toggle ──────────────────────────────────────────────────────────

  el.modeBtns.forEach(function (button) {
    button.addEventListener("click", function () {
      var mode = button.dataset.mode;
      if (mode === state.mode) return;

      state.mode = mode;
      el.modeBtns.forEach(function (other) {
        var active = other === button;
        other.classList.toggle("is-active", active);
        other.setAttribute("aria-checked", active ? "true" : "false");
      });

      addBubble("system", MODE_NOTES[mode] || "");
    });
  });

  // ── Accent / recognition language ────────────────────────────────────────

  function loadLang() {
    var saved = null;
    try { saved = window.localStorage.getItem(LANG_KEY); } catch (err) { /* private mode */ }

    var known = LANGUAGES.some(function (pair) { return pair[0] === saved; });
    state.lang = known ? saved : DEFAULT_LANG;
  }

  function initAccentPicker() {
    if (!el.accent) return;

    LANGUAGES.forEach(function (pair) {
      var option = document.createElement("option");
      option.value = pair[0];
      option.textContent = pair[1];
      el.accent.appendChild(option);
    });
    el.accent.value = state.lang;

    el.accent.addEventListener("change", function () {
      state.lang = el.accent.value;
      try { window.localStorage.setItem(LANG_KEY, state.lang); } catch (err) { /* ignore */ }

      pickVoice();   // match the spoken voice to the chosen variety

      // `lang` is read when a session starts, so cycle recognition to apply it.
      if (recognition) {
        recognition.lang = state.lang;
        if (state.recognizing) {
          var resume = state.wantListening;
          stopRecognition();
          if (resume) window.setTimeout(resumeListening, 300);
        }
      }
    });
  }

  // ── Tutor voice (server speech) ──────────────────────────────────────────

  function initVoicePicker(accents, defaultAccent) {
    if (!el.voice || !el.voicePicker) return;

    var saved = null;
    try { saved = window.localStorage.getItem(VOICE_KEY); } catch (err) { /* ignore */ }

    var valid = accents.some(function (a) { return a.id === saved; });
    state.voiceAccent = valid ? saved : defaultAccent;

    accents.forEach(function (accent) {
      var option = document.createElement("option");
      option.value = accent.id;
      option.textContent = accent.label;
      el.voice.appendChild(option);
    });
    el.voice.value = state.voiceAccent;
    el.voicePicker.hidden = false;

    el.voice.addEventListener("change", function () {
      state.voiceAccent = el.voice.value;
      try { window.localStorage.setItem(VOICE_KEY, state.voiceAccent); } catch (err) { /* ignore */ }
    });
  }

  function loadServerConfig() {
    return fetch("/api/config")
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (config) {
        if (!config || !config.server_speech) return;
        state.serverSpeech = true;
        initVoicePicker(config.accents || [], config.default_accent || "us");
      })
      .catch(function () { /* stay on browser voices */ });
  }

  // ── Typed fallback ───────────────────────────────────────────────────────
  // Keeps the app usable when the Web Speech API is unavailable or blocked.

  el.textForm.addEventListener("submit", function (event) {
    event.preventDefault();
    var text = el.textInput.value.trim();
    if (!text || state.busy) return;
    el.textInput.value = "";
    stopSpeaking();
    sendTurn(text);
  });

  // ── New conversation ─────────────────────────────────────────────────────

  el.newBtn.addEventListener("click", function () {
    stopSpeaking();
    stopRecognition();
    clearError();
    hideTyping();

    state.history = [];
    state.buffer = "";
    state.interim = "";
    state.busy = false;
    el.chat.innerHTML = "";

    seedGreeting();

    if (state.micOn) {
      speak(GREETING);
    } else {
      setStatus("idle");
    }
  });

  // ── Boot ─────────────────────────────────────────────────────────────────

  function seedGreeting() {
    state.history.push({ role: "assistant", content: GREETING });
    addBubble("tutor", GREETING);
  }

  function init() {
    loadLang();
    initAccentPicker();
    loadServerConfig();     // async; browser voices are used until it lands
    syncMicButton();
    seedGreeting();

    if (!SpeechRecognitionCtor) {
      el.micBtn.disabled = true;
      setStatusError("Voice input unavailable");
      showError(
        "This browser does not support the Web Speech API, so SpeakBuddy cannot " +
        "listen. Chrome, Edge, or another Chromium browser works best. You can " +
        "still practise by typing below.",
        false
      );
      el.textInput.focus();
      return;
    }

    if (!window.isSecureContext) {
      showError(
        "Microphone access needs a secure context. Open the app over http://localhost " +
        "or https rather than a file:// path.",
        false
      );
    }

    setStatus("idle");
  }

  init();
})();
