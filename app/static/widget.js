/**
 * YourChatbot Embeddable Widget Script with Integrated Voice Agent
 * Lightweight vanilla JS widget for embedding text chat & AI voice agent on any website.
 */
(function () {
  'use strict';

  if (window.YourChatbotWidgetInitialized) return;
  window.YourChatbotWidgetInitialized = true;

  // ---------------------------------------------------------------------------
  // 1. Script & Environment Configuration
  // ---------------------------------------------------------------------------
  function getScriptConfig() {
    var scripts = document.getElementsByTagName('script');
    var currentScript = document.currentScript;

    if (!currentScript) {
      for (var i = 0; i < scripts.length; i++) {
        if (scripts[i].getAttribute('data-chatbot-id') || scripts[i].getAttribute('data-bot-id')) {
          currentScript = scripts[i];
          break;
        }
      }
      if (!currentScript) currentScript = scripts[scripts.length - 1];
    }

    var botId = currentScript ? (currentScript.getAttribute('data-chatbot-id') || currentScript.getAttribute('data-bot-id')) : 'test-bot';
    if (!botId) botId = 'test-bot';

    var explicitBase = currentScript ? (currentScript.getAttribute('data-api-base') || currentScript.getAttribute('data-backend-url')) : null;
    if (!explicitBase && typeof window !== 'undefined' && window.YCB_API_BASE) {
      explicitBase = window.YCB_API_BASE;
    }

    var apiBase = explicitBase || 'http://localhost:8000';
    if (!explicitBase && currentScript && currentScript.src && currentScript.src.indexOf('http') === 0) {
      try {
        var urlObj = new URL(currentScript.src);
        if (['5173', '5174', '3000', '4173'].indexOf(urlObj.port) !== -1) {
          apiBase = urlObj.protocol + '//' + urlObj.hostname + ':8000';
        } else {
          apiBase = urlObj.origin;
        }
      } catch (e) {}
    }

    return {
      botId: botId,
      apiBase: apiBase,
      defaults: {
        name: 'Support Assistant',
        welcome_message: 'Hi! How can I help you today?',
        theme_color: '#4f46e5',
        avatar_icon: 'support',
        position: 'right',
        bubble_style: 'rounded',
        open_automatically: false,
        pop_after_seconds: 3,
        show_welcome_tooltip: true
      }
    };
  }

  // ---------------------------------------------------------------------------
  // 2. SVG Icon Templates
  // ---------------------------------------------------------------------------
  var Icons = {
    avatar: function (type) {
      if (type === 'faq') {
        return '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
      }
      if (type === 'sales') {
        return '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>';
      }
      return '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 18v-6a9 9 0 0 1 18 0v6"/><path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z"/></svg>';
    },
    message: function () {
      return '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
    },
    mic: function () {
      return '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/></svg>';
    },
    square: function () {
      return '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><rect width="16" height="16" x="4" y="4" rx="3"/></svg>';
    },
    volume: function () {
      return '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a9 9 0 0 1 0 14"/></svg>';
    },
    sparkles: function () {
      return '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg>';
    },
    phoneOff: function () {
      return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.68 13.31a16 16 0 0 0 3.41 2.6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7 2 2 0 0 1 1.72 2v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.42 19.42 0 0 1-6-6 19.8 19.8 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91"/><line x1="22" x2="2" y1="2" y2="22"/></svg>';
    },
    close: function () {
      return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
    },
    refresh: function () {
      return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg>';
    },
    send: function () {
      return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>';
    }
  };

  // ---------------------------------------------------------------------------
  // 3. Markdown Formatting Engine
  // ---------------------------------------------------------------------------
  function renderMarkdown(text) {
    if (!text) return '';
    var html = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    html = html.replace(/^### (.*$)/gim, '<h3 style="font-weight:700;font-size:14px;margin:8px 0 4px 0;color:#FFFFFF;">$1</h3>');
    html = html.replace(/^## (.*$)/gim, '<h2 style="font-weight:700;font-size:15px;margin:10px 0 4px 0;color:#FFFFFF;">$1</h2>');
    html = html.replace(/^# (.*$)/gim, '<h1 style="font-weight:700;font-size:16px;margin:12px 0 6px 0;color:#FFFFFF;">$1</h1>');
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong style="font-weight:700;color:#FFFFFF;">$1</strong>');
    html = html.replace(/__(.*?)__/g, '<strong style="font-weight:700;color:#FFFFFF;">$1</strong>');
    html = html.replace(/\*(.*?)\*/g, '<em style="font-style:italic;color:#E0E7FF;">$1</em>');
    html = html.replace(/`(.*?)`/g, '<code style="background:rgba(255,255,255,0.12);padding:2px 6px;border-radius:4px;font-family:monospace;font-size:12px;color:#A5B4FC;border:1px solid rgba(255,255,255,0.1);">$1</code>');
    html = html.replace(/^\s*[\*\-]\s+(.*$)/gim, '<div style="margin-left:14px;position:relative;padding-left:10px;margin-bottom:3px;color:#F3F6FF;"><span style="position:absolute;left:0;color:#818CF8;">•</span>$1</div>');
    html = html.replace(/\n\n/g, '<div style="margin-bottom:8px;"></div>');
    html = html.replace(/\n/g, '<br/>');

    return html;
  }

  // ---------------------------------------------------------------------------
  // 4. UI Builders & Dynamic Animation Styles
  // ---------------------------------------------------------------------------
  function ensureOrbStyles() {
    if (document.getElementById('ycb-voice-orb-styles')) return;
    var style = document.createElement('style');
    style.id = 'ycb-voice-orb-styles';
    style.textContent =
      '.voice-orb-wrap {' +
        'width: var(--orb-size, 130px);' +
        'height: var(--orb-size, 130px);' +
        'position: relative;' +
        'display: flex;' +
        'align-items: center;' +
        'justify-content: center;' +
        'cursor: pointer;' +
        'outline: none;' +
        'transform: scale(var(--orb-reactive, 1));' +
        'will-change: transform;' +
        'transition: transform 0.08s ease-out;' +
      '}' +
      '.voice-orb {' +
        'position: absolute;' +
        'inset: 0;' +
        'border-radius: 50%;' +
        'animation: orb-breathe 2.8s ease-in-out infinite;' +
        'will-change: transform;' +
      '}' +
      '.voice-orb[data-state="idle"]        { animation: orb-breathe 3.2s ease-in-out infinite; }' +
      '.voice-orb[data-state="connecting"]  { animation: orb-breathe 1.6s ease-in-out infinite; }' +
      '.voice-orb[data-state="listening"]   { animation: orb-swell 1.15s ease-in-out infinite; }' +
      '.voice-orb[data-state="processing"]  { animation: orb-breathe 2.4s ease-in-out infinite; }' +
      '.voice-orb[data-state="speaking"]    { animation: orb-swell 1.7s ease-in-out infinite; }' +
      '.voice-orb[data-state="error"]       { animation: orb-throb 0.9s ease-in-out infinite; }' +
      '@keyframes orb-breathe { 0%,100%{transform:scale(1)} 50%{transform:scale(1.1)} }' +
      '@keyframes orb-swell   { 0%,100%{transform:scale(1)} 50%{transform:scale(1.18)} }' +
      '@keyframes orb-throb   { 0%,100%{transform:scale(0.97)} 50%{transform:scale(1.08)} }' +
      '.voice-orb__glow {' +
        'position: absolute;' +
        'inset: -16%;' +
        'border-radius: 50%;' +
        'background: radial-gradient(circle, var(--orb-color-main, #0A84FF), transparent 70%);' +
        'filter: blur(24px);' +
        'opacity: .5;' +
        'animation: orb-glow-pulse 4s ease-in-out infinite;' +
      '}' +
      '@keyframes orb-glow-pulse { 0%,100%{opacity:.4} 50%{opacity:.65} }' +
      '.voice-orb__surface {' +
        'position: absolute;' +
        'inset: 0;' +
        'border-radius: 50%;' +
        'overflow: hidden;' +
        'background: var(--orb-color-light, #F4FBFF);' +
        'box-shadow: inset 0 0 0 1px rgba(255,255,255,.22), 0 10px 34px rgba(0,0,0,.5);' +
      '}' +
      '.voice-orb__blob {' +
        'position: absolute;' +
        'border-radius: 50%;' +
        'filter: blur(18px);' +
        'will-change: transform;' +
      '}' +
      '.voice-orb__blob--main {' +
        'width: 170%;' +
        'height: 170%;' +
        'left: -35%;' +
        'top: 30%;' +
        'background: radial-gradient(circle at 50% 30%, var(--orb-color-main, #0A84FF) 0%, var(--orb-color-main, #0A84FF) 46%, transparent 68%);' +
        'animation: orb-blob-main 7s ease-in-out infinite;' +
      '}' +
      '.voice-orb__blob--swirl {' +
        'width: 80%;' +
        'height: 80%;' +
        'left: 40%;' +
        'top: 18%;' +
        'opacity: .75;' +
        'background: radial-gradient(circle, var(--orb-color-main, #0A84FF) 0%, transparent 65%);' +
        'animation: orb-blob-swirl 10s linear infinite;' +
      '}' +
      '.voice-orb__blob--light {' +
        'width: 130%;' +
        'height: 130%;' +
        'left: -20%;' +
        'top: -52%;' +
        'background: radial-gradient(circle at 50% 60%, var(--orb-color-light, #F4FBFF) 0%, rgba(255,255,255,.55) 55%, transparent 75%);' +
        'animation: orb-blob-light 9s ease-in-out infinite;' +
      '}' +
      '.voice-orb__sheen {' +
        'position: absolute;' +
        'inset: 0;' +
        'border-radius: 50%;' +
        'background: radial-gradient(circle at 30% 22%, rgba(255,255,255,.35), transparent 45%);' +
        'pointer-events: none;' +
      '}' +
      '@keyframes orb-blob-main { 0%,100%{transform:translate(-4%,0) scale(1)} 33%{transform:translate(3%,3%) scale(1.06) rotate(2deg)} 66%{transform:translate(-2%,-3%) scale(.97) rotate(-2deg)} }' +
      '@keyframes orb-blob-swirl { from{transform:rotate(0) translateX(0)} 25%{transform:rotate(90deg) translateX(6%)} 50%{transform:rotate(180deg) translateX(0)} 75%{transform:rotate(270deg) translateX(-6%)} to{transform:rotate(360deg) translateX(0)} }' +
      '@keyframes orb-blob-light { 0%,100%{transform:translate(0,0) scale(1)} 33%{transform:translate(5%,7%) scale(1.05)} 66%{transform:translate(-6%,2%) scale(.96)} }' +
      '.voice-orb__content {' +
        'position: absolute;' +
        'inset: 0;' +
        'display: flex;' +
        'align-items: center;' +
        'justify-content: center;' +
        'z-index: 2;' +
        'color: #0A84FF;' +
        'filter: drop-shadow(0 1px 2px rgba(255,255,255,.35));' +
      '}';
    document.head.appendChild(style);
  }

  function buildTooltipHtml(config) {
    if (!config.show_welcome_tooltip) return '';
    var posLeft = config.position === 'left';
    return '<div id="ycb-tooltip" style="position: absolute; bottom: 76px; ' + (posLeft ? 'left: 0;' : 'right: 0;') + ' background: #091121; color: #F3F6FF; padding: 10px 14px; border-radius: 12px; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4); font-size: 13px; font-weight: 500; white-space: nowrap; border: 1px solid #1C2C4B; pointer-events: none; opacity: 1; transition: opacity 0.2s;">' +
      config.welcome_message +
      '<div style="position: absolute; bottom: -6px; ' + (posLeft ? 'left: 20px;' : 'right: 20px;') + ' width: 10px; height: 10px; background: #091121; border-right: 1px solid #1C2C4B; border-bottom: 1px solid #1C2C4B; transform: rotate(45deg);"></div>' +
      '</div>';
  }

  function buildLauncherHtml(config) {
    var borderRadius = '16px';
    if (config.bubble_style === 'pill') borderRadius = '50%';
    if (config.bubble_style === 'square') borderRadius = '6px';

    return '<div id="ycb-launcher-group">' +
      '<button id="ycb-launcher" style="width: 56px; height: 56px; border-radius: ' + borderRadius + '; background-color: ' + config.theme_color + '; color: #ffffff; border: none; outline: none; cursor: pointer; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3); display: flex; align-items: center; justify-content: center; transition: transform 0.2s;" title="Open Chat">' +
        Icons.message() +
      '</button>' +
    '</div>';
  }

  function buildChatWindowHtml(config) {
    var posLeft = config.position === 'left';
    return '<div id="ycb-window" style="display: none; width: 375px; height: 530px; max-width: calc(100vw - 32px); max-height: calc(100vh - 90px); background: #080E1B; color: #F3F6FF; border-radius: 20px; box-shadow: 0 20px 35px -10px rgba(0, 0, 0, 0.5); border: 1px solid #1C2C4B; overflow: hidden; flex-direction: column; position: absolute; bottom: 0; ' + (posLeft ? 'left: 0;' : 'right: 0;') + ' z-index: 10;">' +
      // Header
      '<div style="background-color: #091121; color: #F3F6FF; padding: 14px 16px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #1C2C4B; flex-shrink: 0;">' +
        '<div style="display: flex; align-items: center; gap: 10px;">' +
          '<div style="width: 36px; height: 36px; border-radius: 10px; background-color: ' + config.theme_color + '; color: #ffffff; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">' +
            Icons.avatar(config.avatar_icon) +
          '</div>' +
          '<div>' +
            '<div style="font-weight: 700; font-size: 14px; color: #F3F6FF; line-height: 1.2;">' + config.name + '</div>' +
            '<div id="ycb-header-sub" style="font-size: 10px; color: #71829F; margin-top: 2px;">AI Assistant Online</div>' +
          '</div>' +
        '</div>' +
        '<div style="display: flex; align-items: center; gap: 6px;">' +
          '<button id="ycb-toggle-mode" title="Switch Mode" style="background: #101D39; border: 1px solid #1C2C4B; color: #C7D2FE; font-size: 11px; font-weight: 600; padding: 4px 8px; border-radius: 8px; cursor: pointer; display: flex; align-items: center; gap: 4px;">' +
            '<span id="ycb-mode-btn-text">Voice</span>' +
          '</button>' +
          '<button id="ycb-refresh" title="Reset chat" style="background: transparent; border: none; color: #71829F; cursor: pointer; width: 28px; height: 28px; border-radius: 6px; display: flex; align-items: center; justify-content: center;">' +
            Icons.refresh() +
          '</button>' +
          '<button id="ycb-close" title="Close" style="background: transparent; border: none; color: #71829F; cursor: pointer; width: 28px; height: 28px; border-radius: 6px; display: flex; align-items: center; justify-content: center;">' +
            Icons.close() +
          '</button>' +
        '</div>' +
      '</div>' +

      // Text Chat View
      '<div id="ycb-chat-view" style="display: flex; flex-direction: column; flex: 1; min-height: 0;">' +
        '<div id="ycb-messages" style="flex: 1; padding: 14px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; background-color: #080E1B;"></div>' +
        '<div style="padding: 10px 12px 6px 12px; background: #091121; border-top: 1px solid #1C2C4B; flex-shrink: 0;">' +
          '<form id="ycb-form" style="display: flex; align-items: center; gap: 6px; margin-bottom: 6px;">' +
            '<input id="ycb-input" type="text" placeholder="Type a message or tap mic..." style="flex: 1; border: 1px solid #1C2C4B; border-radius: 10px; padding: 9px 12px; font-size: 13px; outline: none; background: #101D39; color: #F3F6FF;" />' +
            '<button type="button" id="ycb-mic-trigger" style="width: 36px; height: 36px; border-radius: 10px; background: #142342; border: 1px solid #243653; color: #22D3EE; cursor: pointer; display: flex; align-items: center; justify-content: center;" title="Voice Mode">' +
              Icons.mic() +
            '</button>' +
            '<button type="submit" id="ycb-send" style="width: 36px; height: 36px; border-radius: 10px; background-color: ' + config.theme_color + '; color: #ffffff; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center;">' +
              Icons.send() +
            '</button>' +
          '</form>' +
          '<div style="display: flex; justify-content: space-between; align-items: center; font-size: 10px; color: #71829F; padding: 0 2px;">' +
            '<span>Shift + Enter for new line</span>' +
            '<span style="font-weight: 500; color: #818CF8;">Powered by yourchatbot</span>' +
          '</div>' +
        '</div>' +
      '</div>' +

      // Voice Agent View
      '<div id="ycb-voice-view" style="display: none; flex-direction: column; flex: 1; min-height: 0; background: radial-gradient(circle at center, #091121 0%, #080E1B 100%); padding: 18px 20px; align-items: center; justify-content: space-between; position: relative; overflow: hidden;">' +
        // Ambient background glow
        '<div id="ycb-ambient-glow" style="position: absolute; width: 220px; height: 220px; border-radius: 50%; filter: blur(36px); opacity: 0.25; pointer-events: none; transition: background 0.5s ease; background: ' + config.theme_color + ';"></div>' +

        '<div style="text-align: center; margin-top: 6px; z-index: 2;">' +
          '<div id="ycb-voice-status-title" style="font-size: 15px; font-weight: 700; color: #F3F6FF; letter-spacing: -0.01em;">Tap to Speak</div>' +
          '<div id="ycb-voice-status-sub" style="font-size: 11px; color: #71829F; margin-top: 4px;">Speak clearly into your microphone</div>' +
        '</div>' +

        // Liquid Voice Orb Visualizer matching dedicated preview page
        '<div style="position: relative; display: flex; align-items: center; justify-content: center; margin: 18px 0; z-index: 2;">' +
          '<div id="ycb-orb-wrap" class="voice-orb-wrap" style="--orb-size: 130px; --orb-color-main: #0A84FF; --orb-color-light: #F4FBFF;">' +
            '<div id="ycb-orb" class="voice-orb" data-state="idle">' +
              '<div class="voice-orb__glow"></div>' +
              '<div class="voice-orb__surface">' +
                '<div class="voice-orb__blob voice-orb__blob--main"></div>' +
                '<div class="voice-orb__blob voice-orb__blob--swirl"></div>' +
                '<div class="voice-orb__blob voice-orb__blob--light"></div>' +
                '<div class="voice-orb__sheen"></div>' +
              '</div>' +
              '<div id="ycb-orb-content" class="voice-orb__content">' +
                Icons.mic() +
              '</div>' +
            '</div>' +
          '</div>' +
        '</div>' +

        // End Call Button
        '<div style="margin-bottom: 8px; z-index: 2;">' +
          '<button id="ycb-voice-end-btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px; background: rgba(244, 63, 94, 0.12); color: #fda4af; border: 1px solid rgba(244, 63, 94, 0.3); border-radius: 12px; font-size: 11px; font-weight: 600; cursor: pointer; transition: all 0.2s; outline: none;" title="Hang Up / Cut Call">' +
            Icons.phoneOff() +
            '<span>Cut Call</span>' +
          '</button>' +
        '</div>' +

        // Spoken Transcript Box
        '<div style="width: 100%; max-height: 95px; background: rgba(9, 17, 33, 0.85); border: 1px solid #1C2C4B; border-radius: 12px; padding: 10px 14px; overflow-y: auto; z-index: 2; box-sizing: border-box;">' +
          '<div style="font-size: 10px; font-weight: 700; text-transform: uppercase; color: #71829F; margin-bottom: 4px; display: flex; align-items: center; gap: 4px;">' +
            Icons.sparkles() +
            '<span>Live Conversation Transcript</span>' +
          '</div>' +
          '<div id="ycb-voice-transcript" style="font-size: 12px; color: #F3F6FF; line-height: 1.4;">Waiting for your question...</div>' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  // ---------------------------------------------------------------------------
  // 5. Main Widget Application Controller
  // ---------------------------------------------------------------------------
  function initializeWidgetApp() {
    var envConfig = getScriptConfig();
    var botId = envConfig.botId;
    var apiBase = envConfig.apiBase;
    var config = envConfig.defaults;

    var isOpen = false;
    var currentMode = 'chat'; // 'chat' or 'voice'
    var activeConversationId = null;
    var voiceSessionId = null;
    var currentVoiceTurnId = null;
    var lastSpokenUserTurnId = null;
    var lastSpokenUserText = '';
    var isRecording = false;
    var mediaRecorder = null;
    var audioChunks = [];
    var currentAudio = null;
    var voiceGreeted = false;
    var lastAppendedMsg = { role: null, text: '' };

    var rootContainer = document.createElement('div');
    rootContainer.id = 'yourchatbot-widget-root';
    rootContainer.style.position = 'fixed';
    rootContainer.style.bottom = '24px';
    rootContainer.style.zIndex = '999999';
    rootContainer.style.fontFamily = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';

    function renderUI() {
      ensureOrbStyles();
      rootContainer.style.left = config.position === 'left' ? '24px' : 'auto';
      rootContainer.style.right = config.position === 'right' ? '24px' : 'auto';
      rootContainer.innerHTML = buildTooltipHtml(config) + buildLauncherHtml(config) + buildChatWindowHtml(config);
      document.body.appendChild(rootContainer);

      bindEvents();
      resetMessages();
    }

    var launcherGroup, launcherBtn, voiceLauncherBtn, windowEl, closeBtn, refreshBtn, toggleModeBtn, modeBtnText;
    var formEl, inputEl, micTriggerBtn, messagesEl, tooltipEl, headerSub;
    var chatView, voiceView, orbWrapEl, orbEl, orbContentEl, ambientGlowEl, voiceEndBtn;
    var voiceStatusTitle, voiceStatusSub, voiceTranscript;
    var currentAssistantMsgBubble = null;

    function bindEvents() {
      launcherGroup = document.getElementById('ycb-launcher-group');
      launcherBtn = document.getElementById('ycb-launcher');
      voiceLauncherBtn = document.getElementById('ycb-voice-launcher');
      windowEl = document.getElementById('ycb-window');
      closeBtn = document.getElementById('ycb-close');
      refreshBtn = document.getElementById('ycb-refresh');
      toggleModeBtn = document.getElementById('ycb-toggle-mode');
      modeBtnText = document.getElementById('ycb-mode-btn-text');
      headerSub = document.getElementById('ycb-header-sub');

      formEl = document.getElementById('ycb-form');
      inputEl = document.getElementById('ycb-input');
      micTriggerBtn = document.getElementById('ycb-mic-trigger');
      messagesEl = document.getElementById('ycb-messages');
      tooltipEl = document.getElementById('ycb-tooltip');

      chatView = document.getElementById('ycb-chat-view');
      voiceView = document.getElementById('ycb-voice-view');
      orbWrapEl = document.getElementById('ycb-orb-wrap');
      orbEl = document.getElementById('ycb-orb');
      orbContentEl = document.getElementById('ycb-orb-content');
      ambientGlowEl = document.getElementById('ycb-ambient-glow');
      voiceEndBtn = document.getElementById('ycb-voice-end-btn');
      voiceStatusTitle = document.getElementById('ycb-voice-status-title');
      voiceStatusSub = document.getElementById('ycb-voice-status-sub');
      voiceTranscript = document.getElementById('ycb-voice-transcript');

      launcherBtn.addEventListener('click', function () { openWidget('chat'); });
      if (voiceLauncherBtn) {
        voiceLauncherBtn.addEventListener('click', function () { openWidget('voice'); });
      }
      closeBtn.addEventListener('click', function () { closeWidget(); });
      refreshBtn.addEventListener('click', function () { resetMessages(); });
      toggleModeBtn.addEventListener('click', function () {
        setWidgetMode(currentMode === 'chat' ? 'voice' : 'chat');
      });
      micTriggerBtn.addEventListener('click', function () { setWidgetMode('voice'); });
      formEl.addEventListener('submit', handleMessageSubmit);
      if (orbWrapEl) {
        orbWrapEl.addEventListener('click', handleVoiceMicClick);
      }
      if (voiceEndBtn) {
        voiceEndBtn.addEventListener('click', endVoiceCall);
      }

      if (config.open_automatically) {
        var delay = (config.pop_after_seconds || 3) * 1000;
        setTimeout(function () {
          if (!isOpen) openWidget('chat');
        }, delay);
      }
    }

    function openWidget(mode) {
      isOpen = true;
      windowEl.style.display = 'flex';
      launcherGroup.style.display = 'none';
      if (tooltipEl) tooltipEl.style.display = 'none';
      setWidgetMode(mode || 'chat');
    }

    function closeWidget() {
      isOpen = false;
      stopAudioPlayback();
      stopVoiceStreaming();
      if (voiceWs) {
        try { voiceWs.close(); } catch (e) {}
        voiceWs = null;
      }
      if (isRecording) stopVoiceRecording();
      windowEl.style.display = 'none';
      launcherGroup.style.display = 'flex';
      if (tooltipEl && config.show_welcome_tooltip) tooltipEl.style.display = 'block';
    }

    var voiceWs = null;
    var micStream = null;
    var micAudioCtx = null;
    var micProcessor = null;
    var assistantSpeakingStartTime = 0;

    function downsampleTo16k(input, inputSampleRate) {
      if (inputSampleRate === 16000) {
        var out = new Int16Array(input.length);
        for (var i = 0; i < input.length; i++) {
          var s = Math.max(-1, Math.min(1, input[i]));
          out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        return out;
      }
      var ratio = inputSampleRate / 16000;
      var newLength = Math.round(input.length / ratio);
      var out = new Int16Array(newLength);
      for (var j = 0; j < newLength; j++) {
        var originalIdx = j * ratio;
        var leftIdx = Math.floor(originalIdx);
        var rightIdx = Math.min(leftIdx + 1, input.length - 1);
        var weight = originalIdx - leftIdx;
        var sample = input[leftIdx] * (1 - weight) + input[rightIdx] * weight;
        var s2 = Math.max(-1, Math.min(1, sample));
        out[j] = s2 < 0 ? s2 * 0x8000 : s2 * 0x7fff;
      }
      return out;
    }

    function startVoiceStreaming(ws) {
      stopVoiceStreaming();
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        console.warn('Microphone recording is not supported in this browser.');
        return;
      }
      navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: false,
          googEchoCancellation: true,
          googExperimentalEchoCancellation: true,
          googAutoGainControl: false,
          googNoiseSuppression: true,
          googHighpassFilter: true
        }
      })
      .then(function (stream) {
        micStream = stream;
        var AudioCtx = window.AudioContext || window.webkitAudioContext;
        micAudioCtx = new AudioCtx();
        if (micAudioCtx.state === 'suspended') {
          micAudioCtx.resume().catch(function () {});
        }
        var source = micAudioCtx.createMediaStreamSource(stream);
        var processor = micAudioCtx.createScriptProcessor(4096, 1, 1);
        micProcessor = processor;

        processor.onaudioprocess = function (e) {
          if (!ws || ws.readyState !== WebSocket.OPEN) return;
          var channelData = e.inputBuffer.getChannelData(0);

          var sumSquares = 0;
          for (var i = 0; i < channelData.length; i++) sumSquares += channelData[i] * channelData[i];
          var norm = Math.min(100, Math.round(Math.sqrt(sumSquares / channelData.length) * 350));
          if (orbWrapEl) {
            var reactive = 1 + (Math.max(0, Math.min(100, norm)) / 100) * 0.24;
            orbWrapEl.style.setProperty('--orb-reactive', reactive);
          }

          // Downsample input rate to 16,000 Hz Mono signed 16-bit PCM.
          // Stream microphone audio continuously to the server; the backend Silero VAD,
          // echo cancellation guard, and Deepgram STT verify genuine user speech for barge-in.
          var pcm16 = downsampleTo16k(channelData, micAudioCtx.sampleRate);
          try {
            ws.send(pcm16.buffer);
          } catch (err) {
            console.error('[Voice WS] Mic send error:', err);
          }
        };

        source.connect(processor);
        var muteGain = micAudioCtx.createGain();
        muteGain.gain.value = 0;
        processor.connect(muteGain);
        muteGain.connect(micAudioCtx.destination);
      })
      .catch(function (err) {
        console.warn('[Voice WS] Microphone permission note:', err);
        voiceTranscript.innerHTML = '<span style="color:#fb7185;">Please allow microphone permissions to speak.</span>';
      });
    }

    function stopVoiceStreaming() {
      if (micProcessor) {
        try { micProcessor.disconnect(); } catch (e) {}
        micProcessor = null;
      }
      if (micAudioCtx) {
        try { micAudioCtx.close(); } catch (e) {}
        micAudioCtx = null;
      }
      if (micStream) {
        try { micStream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}
        micStream = null;
      }
    }

    function setWidgetMode(mode) {
      currentMode = mode;
      if (currentMode === 'voice') {
        pcmPlayer.init();
        chatView.style.display = 'none';
        voiceView.style.display = 'flex';
        modeBtnText.innerText = 'Chat';
        headerSub.innerText = 'Pipecat Voice Agent';
        initVoiceAgentWs();
      } else {
        voiceView.style.display = 'none';
        chatView.style.display = 'flex';
        modeBtnText.innerText = 'Voice';
        headerSub.innerText = 'AI Assistant Online';
        stopAudioPlayback();
        stopVoiceStreaming();
        if (voiceWs) {
          try { voiceWs.close(); } catch(e){}
          voiceWs = null;
        }
        inputEl.focus();
      }
    }

    var pcmPlayer = {
      ctx: null,
      gainNode: null,
      nextTime: 0,
      activeSources: [],
      currentPlaybackRms: 0,
      onPlaybackStart: null,
      onPlaybackEnd: null,
      playingNotified: false,
      carry: null,

      init: function () {
        var AC = window.AudioContext || window.webkitAudioContext;
        if (!this.ctx || this.ctx.state === 'closed') {
          this.ctx = new AC();
          this.gainNode = this.ctx.createGain();
          this.gainNode.connect(this.ctx.destination);
          this.nextTime = 0;
        }
        if (this.ctx.state === 'suspended') {
          this.ctx.resume().catch(function () {});
        }
      },
      setVolume: function (vol) {
        if (this.gainNode && this.ctx) {
          this.gainNode.gain.setValueAtTime(vol, this.ctx.currentTime);
        }
      },
      play: function (buffer) {
        this.init();
        var ctx = this.ctx, self = this;
        if (ctx.state === 'suspended') ctx.resume().catch(function () {});

        var incoming = new Uint8Array(buffer);
        var bytes = new Uint8Array(incoming.length + (this.carry === null ? 0 : 1));
        var off = 0;
        if (this.carry !== null) { bytes[0] = this.carry; off = 1; this.carry = null; }
        bytes.set(incoming, off);
        if (bytes.length % 2 === 1) this.carry = bytes[bytes.length - 1];
        var usable = bytes.length - (bytes.length % 2);
        if (!usable) return;
        var int16 = new Int16Array(bytes.buffer, bytes.byteOffset, usable / 2);
        if (int16.length === 0) return;

        var f32 = new Float32Array(int16.length);
        var sumSquares = 0;
        for (var i = 0; i < int16.length; i++) {
          var v = int16[i] / 32768;
          f32[i] = v;
          sumSquares += v * v;
        }
        this.currentPlaybackRms = Math.max(Math.sqrt(sumSquares / int16.length), this.currentPlaybackRms * 0.8);
        if (orbWrapEl) {
          var lvl = Math.min(100, Math.round(this.currentPlaybackRms * 380));
          var reactive = 1 + (lvl / 100) * 0.35;
          orbWrapEl.style.setProperty('--orb-reactive', reactive);
        }

        var audioBuf = ctx.createBuffer(1, f32.length, 24000);
        audioBuf.getChannelData(0).set(f32);
        var src = ctx.createBufferSource();
        src.buffer = audioBuf;
        src.connect(this.gainNode || ctx.destination);
        var now = ctx.currentTime;
        var isFirst = this.activeSources.length === 0;
        // Jitter buffer matching dedicated preview hook: 60ms cushion on first chunk
        var start = isFirst ? (now + 0.06) : Math.max(now, this.nextTime);
        src.start(start);
        this.nextTime = start + audioBuf.duration;

        this.activeSources.push(src);
        if (!this.playingNotified) {
          this.playingNotified = true;
          if (typeof this.onPlaybackStart === 'function') this.onPlaybackStart();
        }
        src.onended = function () {
          var idx = self.activeSources.indexOf(src);
          if (idx !== -1) self.activeSources.splice(idx, 1);
          if (self.activeSources.length === 0) {
            self.currentPlaybackRms = 0;
            if (orbWrapEl) orbWrapEl.style.setProperty('--orb-reactive', 1);
            if (self.playingNotified) {
              self.playingNotified = false;
              if (typeof self.onPlaybackEnd === 'function') self.onPlaybackEnd();
            }
          }
        };
      },
      isPlaying: function () {
        return this.activeSources.length > 0;
      },
      getPlaybackRms: function () {
        return (this.activeSources.length > 0) ? this.currentPlaybackRms : 0;
      },
      stop: function () {
        var wasPlaying = this.playingNotified;
        this.playingNotified = false;
        this.currentPlaybackRms = 0;
        if (orbWrapEl) orbWrapEl.style.setProperty('--orb-reactive', 1);
        for (var i = 0; i < this.activeSources.length; i++) {
          try {
            this.activeSources[i].onended = null;
            this.activeSources[i].stop(0);
            this.activeSources[i].disconnect();
          } catch (e) {}
        }
        this.activeSources = [];
        this.carry = null;
        this.nextTime = 0;
        this.setVolume(1.0);
        if (wasPlaying && typeof this.onPlaybackEnd === 'function') {
          this.onPlaybackEnd();
        }
      }
    };

    function initVoiceAgentWs() {
      pcmPlayer.init();
      var wsProto = apiBase.indexOf('https') === 0 ? 'wss' : 'ws';
      var wsHost = apiBase.replace(/^https?:\/\//, '').split('/')[0];
      var wsUrl = wsProto + '://' + wsHost + '/ws/voice?engine=pipecat&chatbot_id=' + encodeURIComponent(botId);
      if (voiceSessionId) {
        wsUrl += '&session_id=' + encodeURIComponent(voiceSessionId);
      }

      try {
        if (voiceWs) {
          voiceWs.onopen = null;
          voiceWs.onmessage = null;
          voiceWs.onerror = null;
          voiceWs.onclose = null;
          try { voiceWs.close(); } catch(e){}
          voiceWs = null;
        }

        updateVoiceUI('connecting');
        voiceWs = new WebSocket(wsUrl);
        voiceWs.binaryType = 'arraybuffer';

        pcmPlayer.onPlaybackStart = function () {
          if (voiceWs && voiceWs.readyState === WebSocket.OPEN) {
            try { voiceWs.send(JSON.stringify({ type: 'playback', state: 'start' })); } catch (e) {}
          }
        };
        pcmPlayer.onPlaybackEnd = function () {
          if (voiceWs && voiceWs.readyState === WebSocket.OPEN) {
            try { voiceWs.send(JSON.stringify({ type: 'playback', state: 'end' })); } catch (e) {}
          }
        };

        voiceWs.onopen = function () {
          console.info('[Voice WS] Connected; streaming mic');
          updateVoiceUI('idle');
          voiceWs.send(JSON.stringify({ type: 'config', language: 'en' }));
          if (!voiceGreeted) {
            voiceGreeted = true;
            var welcome = config.welcome_message || 'Hello! How can I help you today?';
            voiceWs.send(JSON.stringify({ type: 'greeting', text: welcome }));
          }
          startVoiceStreaming(voiceWs);
        };

        voiceWs.onmessage = function (ev) {
          if (ev.data instanceof ArrayBuffer) {
            if (window.speechSynthesis && window.speechSynthesis.speaking) {
              window.speechSynthesis.cancel();
            }
            updateVoiceUI('speaking');
            pcmPlayer.play(ev.data);
            return;
          }
          if (typeof ev.data === 'string') {
            try {
              var m = JSON.parse(ev.data);
              if (m.type === 'session_created') {
                voiceSessionId = m.session_id;
              } else if (m.type === 'audio_start') {
                if (currentVoiceTurnId && m.turn_id && currentVoiceTurnId !== m.turn_id) {
                  pcmPlayer.stop();
                }
                currentVoiceTurnId = m.turn_id || null;
                pcmPlayer.init();
              } else if (m.type === 'state') {
                if (m.state === 'speaking') {
                  updateVoiceUI('speaking');
                } else if (m.state === 'thinking' || m.state === 'processing') {
                  updateVoiceUI('processing');
                } else if (m.state === 'listening') {
                  updateVoiceUI('listening');
                } else if (m.state === 'idle') {
                  var isSpk = (window.speechSynthesis && window.speechSynthesis.speaking) || pcmPlayer.isPlaying();
                  if (!isSpk) {
                    updateVoiceUI('idle');
                  }
                }
              } else if (m.type === 'duck_audio') {
                pcmPlayer.setVolume(0.65);
              } else if (m.type === 'unduck_audio') {
                pcmPlayer.setVolume(1.0);
              } else if (m.type === 'speech_start') {
                // Visual hint only - authoritative state is driven by server state events
                if (orbRing) orbRing.style.transform = 'scale(1.2)';
              } else if (m.type === 'tts_fallback') {
                if (m.text) {
                  speakFallback(m.text);
                }
              } else if (m.type === 'ping') {
                if (voiceWs && voiceWs.readyState === WebSocket.OPEN) {
                  try { voiceWs.send(JSON.stringify({ type: 'pong' })); } catch (e) {}
                }
              } else if (m.type === 'status') {
                if (m.message) {
                  if (voiceStatusSub) voiceStatusSub.innerText = m.message;
                  if (voiceStatusTitle) voiceStatusTitle.innerText = 'Searching...';
                  if (voiceTranscript) voiceTranscript.innerHTML = '<strong>Agent:</strong> ' + m.message;
                }
              } else if (m.type === 'transcript') {
                if (m.role === 'user') {
                  currentAssistantMsgBubble = null;
                  voiceTranscript.innerHTML = '<strong>You:</strong> ' + m.text;
                  updateVoiceUI('processing');
                  var userTxt = (m.text || '').trim();
                  if (userTxt && !(lastAppendedMsg.role === 'user' && lastAppendedMsg.text === userTxt)) {
                    lastSpokenUserText = userTxt;
                    lastSpokenUserTurnId = m.turn_id || null;
                    appendMessage('user', userTxt);
                  }
                } else {
                  if (m.is_status) {
                    if (voiceStatusSub) voiceStatusSub.innerText = m.text;
                    if (voiceStatusTitle) voiceStatusTitle.innerText = 'Searching...';
                    voiceTranscript.innerHTML = '<strong>Agent:</strong> ' + m.text;
                  } else {
                    if (voiceStatusTitle) voiceStatusTitle.innerText = 'Speaking...';
                    if (voiceStatusSub) voiceStatusSub.innerText = 'Delivering response...';
                    voiceTranscript.innerHTML = '<strong>Agent:</strong> ' + m.text;
                    var agentTxt = (m.text || '').trim();
                    if (!currentAssistantMsgBubble) {
                      if (lastAppendedMsg.role === 'assistant' && lastAppendedMsg.text === agentTxt) {
                        var lastWrap = messagesEl.lastElementChild;
                        currentAssistantMsgBubble = lastWrap ? (lastWrap.querySelector('div') || lastWrap) : null;
                      } else {
                        currentAssistantMsgBubble = appendMessage('assistant', m.text);
                      }
                    } else {
                      currentAssistantMsgBubble.innerHTML = renderMarkdown(m.text);
                      lastAppendedMsg.text = agentTxt;
                      messagesEl.scrollTop = messagesEl.scrollHeight;
                    }
                    if (!m.partial) {
                      currentAssistantMsgBubble = null;
                    }
                  }
                }
              } else if (m.type === 'interrupt') {
                currentAssistantMsgBubble = null;
                stopAudioPlayback();
                updateVoiceUI('listening');
              } else if (m.type === 'turn_end') {
                currentAssistantMsgBubble = null;
                currentVoiceTurnId = null;
                lastSpokenUserTurnId = null;
                lastSpokenUserText = '';
                if (!window.speechSynthesis || !window.speechSynthesis.speaking) {
                  updateVoiceUI('idle');
                }
              } else if (m.type === 'end_call' || m.type === 'call_ended') {
                var endNotice = m.reason === 'inactivity' ? '— Call disconnected due to inactivity —' : '— Call ended —';
                voiceTranscript.innerHTML = '<em>' + endNotice + '</em>';
                stopAudioPlayback();
                stopVoiceStreaming();
                updateVoiceUI('idle');
              } else if (m.type === 'error') {
                console.warn('[Voice WS] Server reported error:', m);
                if (m.code !== 'no_speech_detected' && m.code !== 'tts_failed' && m.code !== 'tts_no_audio') {
                  updateVoiceUI('error');
                }
              }
            } catch (e) {}
          }
        };

        voiceWs.onerror = function (e) {
          console.warn('[Voice WS] Error:', e);
          updateVoiceUI('error');
        };

        voiceWs.onclose = function (ev) {
          stopVoiceStreaming();
          voiceWs = null;
          if (isOpen && currentMode === 'voice') {
            if (ev && ev.code && ev.code !== 1000) {
              updateVoiceUI('error');
            } else {
              updateVoiceUI('idle');
            }
          }
        };
      } catch (e) {
        console.warn('WebSocket init exception:', e);
        updateVoiceUI('error');
      }
    }

    function handleVoiceMicClick() {
      pcmPlayer.init();
      if (micAudioCtx && micAudioCtx.state === 'suspended') {
        micAudioCtx.resume().catch(function () {});
      }
      var isPlaying = (window.speechSynthesis && window.speechSynthesis.speaking) || pcmPlayer.isPlaying();
      if (isPlaying) {
        stopAudioPlayback();
        if (voiceWs && voiceWs.readyState === WebSocket.OPEN) {
          try {
            voiceWs.send(JSON.stringify({
              type: 'interrupt',
              turn_id: currentVoiceTurnId || undefined
            }));
          } catch (e) {}
        }
        updateVoiceUI('listening');
        return;
      }
      if (!voiceWs || voiceWs.readyState !== WebSocket.OPEN) {
        initVoiceAgentWs();
      } else {
        if (!micProcessor) {
          startVoiceStreaming(voiceWs);
        }
        updateVoiceUI('listening');
      }
    }

    function startVoiceRecording() {
      stopAudioPlayback();
      ensureVoiceSession(function () {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
          alert('Microphone recording is not supported in this browser.');
          return;
        }

        navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: false
          }
        })
          .then(function (stream) {
            audioChunks = [];
            var mime = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : '';
            mediaRecorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);

            mediaRecorder.ondataavailable = function (e) {
              if (e.data && e.data.size > 0) audioChunks.push(e.data);
            };

            mediaRecorder.onstop = function () {
              stream.getTracks().forEach(function (t) { t.stop(); });
              isRecording = false;
              updateVoiceUI('processing');

              var blob = new Blob(audioChunks, { type: mime || 'audio/webm' });
              sendVoiceTurn(blob);
            };

            mediaRecorder.start();
            isRecording = true;
            updateVoiceUI('listening');
          })
          .catch(function (err) {
            alert('Please allow microphone permissions to talk with the voice agent.');
          });
      });
    }

    function stopVoiceRecording() {
      if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
      }
    }

    function sendVoiceTurn(audioBlob) {
      var formData = new FormData();
      formData.append('audio', audioBlob, 'turn.webm');
      formData.append('session_id', voiceSessionId);
      formData.append('language', 'en');

      fetch(apiBase + '/api/v1/voice/turn', {
        method: 'POST',
        body: formData
      })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.status === 'repeat') {
          voiceTranscript.innerHTML = '<em>' + (data.message || 'Could not understand audio. Please speak clearly.') + '</em>';
          updateVoiceUI('idle');
          return;
        }

        var userText = data.transcript || '(voice input)';
        var replyText = data.reply || 'No response';
        voiceTranscript.innerHTML = '<strong>You:</strong> ' + userText + '<br/><strong>Agent:</strong> ' + replyText;

        // Also add to text chat messages
        appendMessage('user', userText);
        appendMessage('assistant', replyText);

        if (data.audio_b64) {
          playAudioBase64(data.audio_b64, replyText);
        } else {
          speakFallback(replyText);
        }
      })
      .catch(function () {
        voiceTranscript.innerHTML = '<span style="color:#fb7185;">Voice turn failed. Please tap mic and try again.</span>';
        updateVoiceUI('idle');
      });
    }

    function playAudioBase64(b64, textFallback) {
      stopAudioPlayback();
      try {
        currentAudio = new Audio('data:audio/wav;base64,' + b64);
        updateVoiceUI('speaking');
        currentAudio.onended = function () {
          updateVoiceUI('idle');
          currentAudio = null;
        };
        currentAudio.onerror = function () {
          speakFallback(textFallback);
        };
        currentAudio.play().catch(function () {
          speakFallback(textFallback);
        });
      } catch (e) {
        speakFallback(textFallback);
      }
    }

    function speakFallback(text) {
      if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
        assistantSpeakingStartTime = Date.now();
        var u = new SpeechSynthesisUtterance(text);
        updateVoiceUI('speaking');
        u.onend = function () { updateVoiceUI('idle'); };
        u.onerror = function () { updateVoiceUI('idle'); };
        window.speechSynthesis.speak(u);
      } else {
        updateVoiceUI('idle');
      }
    }

    function stopAudioPlayback() {
      if (pcmPlayer) {
        pcmPlayer.stop();
      }
      if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
      }
      if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
      }
      currentAssistantMsgBubble = null;
    }

    function updateVoiceUI(state) {
      if (orbEl) {
        orbEl.setAttribute('data-state', state);
      }
      var ambientColor = '#0A84FF';
      if (state === 'listening') {
        ambientColor = '#EF4444';
        voiceStatusTitle.innerText = 'Listening to you...';
        voiceStatusSub.innerText = 'Tap orb when done speaking';
        if (orbContentEl) orbContentEl.innerHTML = Icons.square();
      } else if (state === 'processing') {
        ambientColor = '#A855F7';
        voiceStatusTitle.innerText = 'Thinking & processing...';
        voiceStatusSub.innerText = 'Transcribing and executing tools...';
        if (orbContentEl) orbContentEl.innerHTML = Icons.sparkles();
      } else if (state === 'speaking') {
        ambientColor = '#10D6A0';
        voiceStatusTitle.innerText = 'Speaking response...';
        voiceStatusSub.innerText = 'Tap orb to interrupt anytime';
        if (orbContentEl) orbContentEl.innerHTML = Icons.volume();
      } else if (state === 'connecting') {
        ambientColor = '#F59E0B';
        voiceStatusTitle.innerText = 'Connecting...';
        voiceStatusSub.innerText = 'Setting up live voice stream...';
        if (orbContentEl) orbContentEl.innerHTML = Icons.sparkles();
      } else if (state === 'error') {
        ambientColor = '#EF4444';
        voiceStatusTitle.innerText = 'Connection Issue';
        voiceStatusSub.innerText = 'Tap orb to reconnect';
        if (orbContentEl) orbContentEl.innerHTML = Icons.refresh();
      } else {
        ambientColor = config.theme_color || '#0A84FF';
        voiceStatusTitle.innerText = 'Ready to listen';
        voiceStatusSub.innerText = 'Tap orb or speak clearly into microphone';
        if (orbContentEl) orbContentEl.innerHTML = Icons.mic();
      }
      if (ambientGlowEl) {
        ambientGlowEl.style.background = ambientColor;
      }
    }

    function endVoiceCall() {
      if (voiceWs && voiceWs.readyState === WebSocket.OPEN) {
        try { voiceWs.send(JSON.stringify({ type: 'end_call' })); } catch (e) {}
        try { voiceWs.close(1000, 'call_ended'); } catch (e) {}
        voiceWs = null;
      }
      stopAudioPlayback();
      stopVoiceStreaming();
      updateVoiceUI('idle');
      if (voiceTranscript) {
        voiceTranscript.innerHTML = '<em>— Call ended —</em>';
      }
    }

    function resetMessages() {
      if (!messagesEl) return;
      messagesEl.innerHTML = '';
      activeConversationId = null;
      voiceSessionId = null;
      voiceGreeted = false;
      lastAppendedMsg = { role: null, text: '' };
      stopAudioPlayback();
      appendMessage('assistant', config.welcome_message);
    }

    function appendMessage(role, text) {
      var trimmed = (text || '').trim();
      if (!trimmed) return null;
      if (lastAppendedMsg.role === role && lastAppendedMsg.text === trimmed) {
        var lastWrap = messagesEl.lastElementChild;
        return lastWrap ? (lastWrap.querySelector('div') || lastWrap) : null;
      }
      lastAppendedMsg.role = role;
      lastAppendedMsg.text = trimmed;

      var isUser = role === 'user';
      var msgWrap = document.createElement('div');
      msgWrap.style.display = 'flex';
      msgWrap.style.flexDirection = 'column';
      msgWrap.style.alignItems = isUser ? 'flex-end' : 'flex-start';
      msgWrap.style.marginBottom = '4px';

      var bubble = document.createElement('div');
      bubble.style.maxWidth = '85%';
      bubble.style.padding = '10px 14px';
      bubble.style.fontSize = '13px';
      bubble.style.lineHeight = '1.5';

      if (config.bubble_style === 'pill') {
        bubble.style.borderRadius = isUser ? '18px 18px 4px 18px' : '18px 18px 18px 4px';
      } else if (config.bubble_style === 'square') {
        bubble.style.borderRadius = '4px';
      } else {
        bubble.style.borderRadius = isUser ? '14px 14px 4px 14px' : '14px 14px 14px 4px';
      }

      bubble.style.backgroundColor = isUser ? config.theme_color : '#101D39';
      bubble.style.color = isUser ? '#ffffff' : '#F3F6FF';
      bubble.style.border = isUser ? 'none' : '1px solid #1C2C4B';
      bubble.style.wordBreak = 'break-word';

      if (isUser) {
        bubble.style.whiteSpace = 'pre-wrap';
        bubble.innerText = text;
      } else {
        bubble.innerHTML = renderMarkdown(text);
      }

      var timeStamp = document.createElement('span');
      timeStamp.style.fontSize = '10px';
      timeStamp.style.color = '#71829F';
      timeStamp.style.marginTop = '4px';
      timeStamp.style.padding = '0 2px';
      timeStamp.innerText = 'Just now';

      msgWrap.appendChild(bubble);
      msgWrap.appendChild(timeStamp);
      messagesEl.appendChild(msgWrap);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      return bubble;
    }

    function appendTypingIndicator() {
      var id = 'ycb-typing-' + Date.now();
      var msgWrap = document.createElement('div');
      msgWrap.id = id;
      msgWrap.style.display = 'flex';
      msgWrap.style.flexDirection = 'column';
      msgWrap.style.alignItems = 'flex-start';
      msgWrap.style.marginBottom = '4px';

      var bubble = document.createElement('div');
      bubble.className = 'ycb-inner-bubble';
      bubble.style.padding = '8px 12px';
      bubble.style.fontSize = '12px';
      bubble.style.borderRadius = '14px 14px 14px 4px';
      bubble.style.backgroundColor = '#101D39';
      bubble.style.color = '#A3B3CF';
      bubble.style.border = '1px solid #1C2C4B';
      bubble.style.display = 'inline-flex';
      bubble.style.alignItems = 'center';
      bubble.style.gap = '6px';
      bubble.style.fontWeight = '500';

      bubble.innerHTML = '<span style="display:inline-block;width:7px;height:7px;border-radius:50%;background-color:' + config.theme_color + ';box-shadow:0 0 8px ' + config.theme_color + ';"></span><span>Thinking...</span>';

      msgWrap.appendChild(bubble);
      messagesEl.appendChild(msgWrap);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      return id;
    }

    function updateTypingIndicator(id, statusText, toolName) {
      var el = document.getElementById(id);
      if (!el) {
        id = appendTypingIndicator();
        el = document.getElementById(id);
      }
      if (el) {
        var bubble = el.querySelector('.ycb-inner-bubble') || el.querySelector('div');
        if (bubble) {
          var iconHtml = '⚡ ';
          if (toolName === 'web_search' || (statusText && statusText.toLowerCase().indexOf('web') !== -1)) {
            iconHtml = '🔍 ';
          } else if (toolName === 'document_search' || (statusText && (statusText.toLowerCase().indexOf('knowledge') !== -1 || statusText.toLowerCase().indexOf('document') !== -1 || statusText.toLowerCase().indexOf('uploaded') !== -1))) {
            iconHtml = '📚 ';
          }
          bubble.innerHTML = iconHtml + '<span>' + (statusText || 'Thinking...') + '</span>';
        }
      }
    }

    function updateAssistantLiveBubble(id, text) {
      var el = document.getElementById(id);
      if (!el) return;
      var bubble = el.querySelector('.ycb-inner-bubble') || el.querySelector('div');
      if (bubble) {
        bubble.style.maxWidth = '85%';
        bubble.style.padding = '10px 14px';
        bubble.style.fontSize = '13px';
        bubble.style.lineHeight = '1.5';
        bubble.style.backgroundColor = '#101D39';
        bubble.style.color = '#F3F6FF';
        bubble.style.border = '1px solid #1C2C4B';
        bubble.style.wordBreak = 'break-word';
        bubble.style.display = 'block';

        if (config.bubble_style === 'pill') {
          bubble.style.borderRadius = '18px 18px 18px 4px';
        } else if (config.bubble_style === 'square') {
          bubble.style.borderRadius = '4px';
        } else {
          bubble.style.borderRadius = '14px 14px 14px 4px';
        }

        bubble.innerHTML = renderMarkdown(text);
      }

      if (!el.querySelector('.ycb-msg-time')) {
        var timeStamp = document.createElement('span');
        timeStamp.className = 'ycb-msg-time';
        timeStamp.style.fontSize = '10px';
        timeStamp.style.color = '#71829F';
        timeStamp.style.marginTop = '4px';
        timeStamp.style.padding = '0 2px';
        timeStamp.innerText = 'Just now';
        el.appendChild(timeStamp);
      }
    }

    function removeTypingIndicator(id) {
      var el = document.getElementById(id);
      if (el && el.parentNode) {
        el.parentNode.removeChild(el);
      }
    }

    function handleMessageSubmit(e) {
      e.preventDefault();
      var text = inputEl.value.trim();
      if (!text) return;

      inputEl.value = '';
      appendMessage('user', text);

      var typingId = appendTypingIndicator();
      var accumulatedText = '';

      fetch(apiBase + '/chatbot/public/' + botId + '/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, conversation_id: activeConversationId })
      })
      .then(function (res) {
        if (!res.ok) throw new Error('Stream API server returned error');
        var reader = res.body.getReader();
        var decoder = new TextDecoder('utf-8');
        var buffer = '';

        function processChunk(result) {
          if (result.done) {
            return;
          }
          buffer += decoder.decode(result.value, { stream: true });
          var lines = buffer.split('\n');
          buffer = lines.pop();

          for (var i = 0; i < lines.length; i++) {
            var line = lines[i].trim();
            if (line.indexOf('data: ') === 0) {
              try {
                var data = JSON.parse(line.substring(6));
                if (data.type === 'conversation' && data.conversation_id) {
                  activeConversationId = data.conversation_id;
                } else if (data.type === 'status') {
                  updateTypingIndicator(typingId, data.message || 'Thinking...', data.tool);
                } else if (data.type === 'reasoning_delta') {
                  updateTypingIndicator(typingId, 'Thinking...', null);
                } else if (data.type === 'text_delta' && data.delta) {
                  accumulatedText += data.delta;
                  updateAssistantLiveBubble(typingId, accumulatedText);
                  messagesEl.scrollTop = messagesEl.scrollHeight;
                } else if (data.type === 'done') {
                  if (data.message && !accumulatedText) {
                    accumulatedText = data.message;
                  }
                  updateAssistantLiveBubble(typingId, accumulatedText);
                  messagesEl.scrollTop = messagesEl.scrollHeight;
                }
              } catch (err) {}
            }
          }
          return reader.read().then(processChunk);
        }
        return reader.read().then(processChunk);
      })
      .catch(function () {
        // Fallback REST endpoint
        fetch(apiBase + '/chatbot/public/' + botId + '/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text, conversation_id: activeConversationId })
        })
        .then(function (res) { return res.json(); })
        .then(function (data) {
          removeTypingIndicator(typingId);
          if (data.conversation_id) activeConversationId = data.conversation_id;
          appendMessage('assistant', data.message || "Thank you for reaching out! How else can I assist you today?");
        })
        .catch(function () {
          removeTypingIndicator(typingId);
          appendMessage('assistant', "Could not reach assistant. Please try again.");
        });
      });
    }

    // Fetch Chatbot Configuration
    fetch(apiBase + '/chatbot/public/' + botId)
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data) {
          config.name = data.name || config.name;
          config.welcome_message = data.welcome_message || data.description || config.welcome_message;
          config.theme_color = data.theme_color || config.theme_color;
          config.avatar_icon = data.avatar_icon || config.avatar_icon;
          config.position = data.position || config.position;
          config.bubble_style = data.bubble_style || config.bubble_style;
          config.open_automatically = data.open_automatically !== undefined ? data.open_automatically : config.open_automatically;
          config.pop_after_seconds = data.pop_after_seconds || config.pop_after_seconds;
          config.show_welcome_tooltip = data.show_welcome_tooltip !== undefined ? data.show_welcome_tooltip : config.show_welcome_tooltip;
        }
        renderUI();
      })
      .catch(function () {
        renderUI();
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeWidgetApp);
  } else {
    initializeWidgetApp();
  }
})();
