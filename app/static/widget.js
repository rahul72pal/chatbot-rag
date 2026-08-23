/**
 * YourChatbot Embeddable Widget Script
 * Modular, lightweight vanilla JS widget for embedding AI chatbots on any website.
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

    var apiBase = 'http://localhost:8000';
    if (currentScript && currentScript.src && currentScript.src.indexOf('http') === 0) {
      try {
        var urlObj = new URL(currentScript.src);
        apiBase = urlObj.origin;
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
    close: function () {
      return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
    },
    refresh: function () {
      return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg>';
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

    html = html.replace(/^### (.*$)/gim, '<h3 style="font-weight:700;font-size:14px;margin:8px 0 4px 0;color:#0f172a;">$1</h3>');
    html = html.replace(/^## (.*$)/gim, '<h2 style="font-weight:700;font-size:15px;margin:10px 0 4px 0;color:#0f172a;">$1</h2>');
    html = html.replace(/^# (.*$)/gim, '<h1 style="font-weight:700;font-size:16px;margin:12px 0 6px 0;color:#0f172a;">$1</h1>');
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong style="font-weight:700;color:#0f172a;">$1</strong>');
    html = html.replace(/__(.*?)__/g, '<strong style="font-weight:700;color:#0f172a;">$1</strong>');
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
    html = html.replace(/`(.*?)`/g, '<code style="background:rgba(15,23,42,0.06);padding:2px 5px;border-radius:4px;font-family:monospace;font-size:12px;color:#334155;">$1</code>');
    html = html.replace(/^\s*[\*\-]\s+(.*$)/gim, '<div style="margin-left:14px;position:relative;padding-left:10px;margin-bottom:3px;"><span style="position:absolute;left:0;">•</span>$1</div>');
    html = html.replace(/\n\n/g, '<div style="margin-bottom:8px;"></div>');
    html = html.replace(/\n/g, '<br/>');

    return html;
  }

  // ---------------------------------------------------------------------------
  // 4. UI Builders
  // ---------------------------------------------------------------------------
  function buildTooltipHtml(config) {
    if (!config.show_welcome_tooltip) return '';
    var posLeft = config.position === 'left';
    return '<div id="ycb-tooltip" style="position: absolute; bottom: 70px; ' + (posLeft ? 'left: 0;' : 'right: 0;') + ' background: #ffffff; color: #1e293b; padding: 10px 14px; border-radius: 12px; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.12), 0 8px 10px -6px rgba(0, 0, 0, 0.08); font-size: 13px; font-weight: 500; white-space: nowrap; border: 1px solid #e2e8f0; pointer-events: none; opacity: 1; transition: opacity 0.2s;">' +
      config.welcome_message +
      '<div style="position: absolute; bottom: -6px; ' + (posLeft ? 'left: 20px;' : 'right: 20px;') + ' width: 10px; height: 10px; background: #ffffff; border-right: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0; transform: rotate(45deg);"></div>' +
      '</div>';
  }

  function buildLauncherHtml(config) {
    var borderRadius = '16px';
    if (config.bubble_style === 'pill') borderRadius = '50%';
    if (config.bubble_style === 'square') borderRadius = '6px';

    return '<button id="ycb-launcher" style="width: 56px; height: 56px; border-radius: ' + borderRadius + '; background-color: ' + config.theme_color + '; color: #ffffff; border: none; outline: none; cursor: pointer; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.2); display: flex; align-items: center; justify-content: center; transition: transform 0.2s, box-shadow 0.2s;">' +
      Icons.message() +
      '</button>';
  }

  function buildChatWindowHtml(config) {
    var posLeft = config.position === 'left';
    return '<div id="ycb-window" style="display: none; width: 375px; height: 530px; max-width: calc(100vw - 32px); max-height: calc(100vh - 90px); background: #ffffff; border-radius: 20px; box-shadow: 0 20px 30px -10px rgba(0, 0, 0, 0.15); border: 1px solid #e2e8f0; overflow: hidden; flex-direction: column; position: absolute; bottom: 0; ' + (posLeft ? 'left: 0;' : 'right: 0;') + ' z-index: 10;">' +
      '<div style="background-color: #ffffff; color: #0f172a; padding: 16px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #f1f5f9; flex-shrink: 0;">' +
        '<div style="display: flex; align-items: center; gap: 12px;">' +
          '<div style="width: 40px; height: 40px; border-radius: 50%; background-color: ' + config.theme_color + '; color: #ffffff; display: flex; align-items: center; justify-content: center; flex-shrink: 0; shadow: 0 2px 4px rgba(0,0,0,0.1);">' +
            Icons.avatar(config.avatar_icon) +
          '</div>' +
          '<div>' +
            '<div style="font-weight: 700; font-size: 15px; color: #0f172a; line-height: 1.2;">' + config.name + '</div>' +
            '<div style="font-size: 11px; color: #64748b; margin-top: 2px;">Usually replies in minutes</div>' +
          '</div>' +
        '</div>' +
        '<div style="display: flex; align-items: center; gap: 4px;">' +
          '<button id="ycb-refresh" title="Clear chat" style="background: transparent; border: none; color: #64748b; cursor: pointer; width: 32px; height: 32px; border-radius: 8px; display: flex; align-items: center; justify-content: center; transition: background 0.15s;">' +
            Icons.refresh() +
          '</button>' +
          '<button id="ycb-close" title="Close" style="background: transparent; border: none; color: #64748b; cursor: pointer; width: 32px; height: 32px; border-radius: 8px; display: flex; align-items: center; justify-content: center; transition: background 0.15s;">' +
            Icons.close() +
          '</button>' +
        '</div>' +
      '</div>' +
      '<div id="ycb-messages" style="flex: 1; padding: 16px; overflow-y: auto; display: flex; flex-direction: column; gap: 14px; background-color: #f8fafc; align-items: stretch;"></div>' +
      '<div style="padding: 12px 14px 8px 14px; background: #ffffff; border-top: 1px solid #f1f5f9; flex-shrink: 0;">' +
        '<form id="ycb-form" style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">' +
          '<input id="ycb-input" type="text" placeholder="Type a message..." style="flex: 1; border: 1px solid #e2e8f0; border-radius: 12px; padding: 11px 16px; font-size: 13.5px; outline: none; background: #ffffff; color: #0f172a; transition: border-color 0.2s;" />' +
          '<button type="submit" id="ycb-send" style="width: 40px; height: 40px; border-radius: 12px; background-color: ' + config.theme_color + '; color: #ffffff; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">' +
            Icons.send() +
          '</button>' +
        '</form>' +
        '<div style="display: flex; justify-content: space-between; align-items: center; font-size: 10px; color: #94a3b8; padding: 0 4px;">' +
          '<span>Shift + Enter for new line</span>' +
          '<span style="font-weight: 500;">Powered by yourchatbot</span>' +
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
    var activeConversationId = null;

    var rootContainer = document.createElement('div');
    rootContainer.id = 'yourchatbot-widget-root';
    rootContainer.style.position = 'fixed';
    rootContainer.style.bottom = '24px';
    rootContainer.style.zIndex = '999999';
    rootContainer.style.fontFamily = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';

    function renderUI() {
      rootContainer.style.left = config.position === 'left' ? '24px' : 'auto';
      rootContainer.style.right = config.position === 'right' ? '24px' : 'auto';
      rootContainer.innerHTML = buildTooltipHtml(config) + buildLauncherHtml(config) + buildChatWindowHtml(config);
      document.body.appendChild(rootContainer);

      bindEvents();
      resetMessages();
    }

    var launcherBtn, windowEl, closeBtn, refreshBtn, formEl, inputEl, messagesEl, tooltipEl;

    function bindEvents() {
      launcherBtn = document.getElementById('ycb-launcher');
      windowEl = document.getElementById('ycb-window');
      closeBtn = document.getElementById('ycb-close');
      refreshBtn = document.getElementById('ycb-refresh');
      formEl = document.getElementById('ycb-form');
      inputEl = document.getElementById('ycb-input');
      messagesEl = document.getElementById('ycb-messages');
      tooltipEl = document.getElementById('ycb-tooltip');

      launcherBtn.addEventListener('click', function () { toggleChat(true); });
      closeBtn.addEventListener('click', function () { toggleChat(false); });
      refreshBtn.addEventListener('click', function () { resetMessages(); });
      formEl.addEventListener('submit', handleMessageSubmit);

      if (config.open_automatically) {
        var delay = (config.pop_after_seconds || 3) * 1000;
        setTimeout(function () {
          if (!isOpen) toggleChat(true);
        }, delay);
      }
    }

    function toggleChat(show) {
      isOpen = show;
      if (isOpen) {
        windowEl.style.display = 'flex';
        launcherBtn.style.display = 'none';
        if (tooltipEl) tooltipEl.style.display = 'none';
        inputEl.focus();
      } else {
        windowEl.style.display = 'none';
        launcherBtn.style.display = 'flex';
        if (tooltipEl && config.show_welcome_tooltip) tooltipEl.style.display = 'block';
      }
    }

    function resetMessages() {
      if (!messagesEl) return;
      messagesEl.innerHTML = '';
      activeConversationId = null;
      appendMessage('assistant', config.welcome_message);
    }

    function appendMessage(role, text) {
      var isUser = role === 'user';
      var msgWrap = document.createElement('div');
      msgWrap.style.display = 'flex';
      msgWrap.style.flexDirection = 'column';
      msgWrap.style.alignItems = isUser ? 'flex-end' : 'flex-start';
      msgWrap.style.marginBottom = '4px';

      var bubble = document.createElement('div');
      bubble.style.maxWidth = '85%';
      bubble.style.padding = '12px 16px';
      bubble.style.fontSize = '13.5px';
      bubble.style.lineHeight = '1.5';

      if (config.bubble_style === 'pill') {
        bubble.style.borderRadius = isUser ? '20px 20px 4px 20px' : '20px 20px 20px 4px';
      } else if (config.bubble_style === 'square') {
        bubble.style.borderRadius = '4px';
      } else {
        bubble.style.borderRadius = isUser ? '16px 16px 4px 16px' : '16px 16px 16px 4px';
      }

      bubble.style.backgroundColor = isUser ? config.theme_color : '#ffffff';
      bubble.style.color = isUser ? '#ffffff' : '#0f172a';
      bubble.style.boxShadow = isUser ? 'none' : '0 2px 8px rgba(0, 0, 0, 0.04)';
      bubble.style.border = isUser ? 'none' : '1px solid #e2e8f0';
      bubble.style.wordBreak = 'break-word';

      if (isUser) {
        bubble.style.whiteSpace = 'pre-wrap';
        bubble.innerText = text;
      } else {
        bubble.innerHTML = renderMarkdown(text);
      }

      var timeStamp = document.createElement('span');
      timeStamp.style.fontSize = '10px';
      timeStamp.style.color = '#94a3b8';
      timeStamp.style.marginTop = '4px';
      timeStamp.style.padding = '0 2px';
      timeStamp.innerText = 'Just now';

      msgWrap.appendChild(bubble);
      msgWrap.appendChild(timeStamp);
      messagesEl.appendChild(msgWrap);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function appendTypingIndicator() {
      var id = 'ycb-typing-' + Date.now();
      var msgWrap = document.createElement('div');
      msgWrap.id = id;
      msgWrap.style.display = 'flex';
      msgWrap.style.flexDirection = 'column';
      msgWrap.style.alignItems = 'flex-start';
      msgWrap.style.marginBottom = '6px';

      var bubble = document.createElement('div');
      bubble.className = 'ycb-inner-bubble';
      bubble.style.padding = '8px 12px';
      bubble.style.fontSize = '12px';
      bubble.style.borderRadius = '14px';
      bubble.style.backgroundColor = '#f1f5f9';
      bubble.style.color = '#475569';
      bubble.style.border = '1px solid #e2e8f0';
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
          } else if (toolName === 'document_search' || (statusText && statusText.toLowerCase().indexOf('knowledge') !== -1)) {
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
        bubble.style.padding = '12px 16px';
        bubble.style.fontSize = '13.5px';
        bubble.style.lineHeight = '1.5';
        bubble.style.backgroundColor = '#ffffff';
        bubble.style.color = '#0f172a';
        bubble.style.boxShadow = '0 2px 8px rgba(0, 0, 0, 0.04)';
        bubble.style.border = '1px solid #e2e8f0';
        bubble.style.wordBreak = 'break-word';
        bubble.style.display = 'block';

        if (config.bubble_style === 'pill') {
          bubble.style.borderRadius = '20px 20px 20px 4px';
        } else if (config.bubble_style === 'square') {
          bubble.style.borderRadius = '4px';
        } else {
          bubble.style.borderRadius = '16px 16px 16px 4px';
        }

        bubble.innerHTML = renderMarkdown(text);
      }
    }

    function removeTypingIndicator(id) {
      var typingEls = messagesEl.querySelectorAll('[id^="ycb-typing-"]');
      for (var i = 0; i < typingEls.length; i++) {
        if (typingEls[i].parentNode) {
          typingEls[i].parentNode.removeChild(typingEls[i]);
        }
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
          appendMessage('assistant', "We are getting Some server issue Please Contact the owner");
        });
      });
    }

    // Fetch Chatbot Configuration
    fetch(apiBase + '/chatbot/public/' + botId)
      .then(function (res) {
        if (!res.ok) throw new Error('Fetch chatbot config failed');
        return res.json();
      })
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
