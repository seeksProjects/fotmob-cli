"""Web server — serves the FotMob CLI as a web UI.

Run: python web.py
Uses query_handler.py for ALL query processing (same as terminal CLI).
"""

import sys
import os
import logging

from flask import Flask, request, jsonify, render_template_string

logging.getLogger("werkzeug").setLevel(logging.WARNING)
sys.path.insert(0, os.path.dirname(__file__))

from query_handler import handle_query

app = Flask(__name__)


# ============================================================================
# HTML TEMPLATE
# ============================================================================

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>FotMob CLI</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { height: 100vh; display: flex; flex-direction: column; font-size: 14px; transition: all 0.3s; }

        #header {
            display: flex; align-items: center; justify-content: space-between;
            padding: 10px 16px; z-index: 10;
        }
        #header h1 { font-size: 16px; margin: 0; }
        #mode-toggle {
            background: none; border: 1px solid; border-radius: 20px;
            padding: 4px 14px; font-size: 12px; cursor: pointer; transition: all 0.3s;
        }

        #output { flex: 1; overflow-y: auto; padding: 12px 16px; }

        #input-bar { display: flex; padding: 8px 12px; align-items: center; gap: 8px; }
        #query-input {
            flex: 1; border: none; outline: none; font-size: 16px; padding: 10px 14px;
            border-radius: 24px; transition: all 0.3s;
        }
        #send-btn {
            width: 42px; height: 42px; border-radius: 50%; border: none;
            font-size: 18px; cursor: pointer; transition: all 0.3s;
            display: flex; align-items: center; justify-content: center;
        }
        #send-btn:disabled { opacity: 0.4; }

        /* ========== TERMINAL ========== */
        body.terminal {
            background: #0d1117; color: #c9d1d9;
            font-family: 'Courier New', 'Consolas', monospace;
        }
        .terminal #header { background: #0d1117; border-bottom: 1px solid #30363d; }
        .terminal #header h1 { color: #58a6ff; }
        .terminal #mode-toggle { color: #8b949e; border-color: #30363d; }
        .terminal #output { white-space: pre-wrap; word-wrap: break-word; line-height: 1.5; }
        .terminal #input-bar { background: #161b22; border-top: 1px solid #30363d; }
        .terminal #query-input {
            background: transparent; color: #c9d1d9; border-radius: 0;
            font-family: 'Courier New', 'Consolas', monospace; padding: 8px 0;
        }
        .terminal #query-input::placeholder { color: #484f58; }
        .terminal #send-btn {
            background: #238636; color: white; border-radius: 6px;
            width: auto; height: auto; padding: 8px 16px; font-size: 14px;
            font-family: 'Courier New', 'Consolas', monospace;
        }
        .terminal .msg { margin-bottom: 6px; }
        .terminal .msg.user { color: #3fb950; }
        .terminal .msg.user::before { content: "> "; }
        .terminal .msg.bot { color: #c9d1d9; white-space: pre-wrap; }
        .terminal .msg.loading { color: #8b949e; font-style: italic; }
        .terminal .msg.error { color: #f85149; }

        /* ========== CHAT ========== */
        body.chat {
            background: #e5ddd5;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            color: #111;
        }
        .chat #header { background: #075e54; color: white; }
        .chat #header h1 { color: white; font-size: 17px; }
        .chat #mode-toggle { color: rgba(255,255,255,0.8); border-color: rgba(255,255,255,0.4); }
        .chat #output { background: #e5ddd5; padding: 16px; }
        .chat #input-bar { background: #f0f0f0; border-top: 1px solid #d1d1d1; }
        .chat #query-input { background: white; color: #111; }
        .chat #query-input::placeholder { color: #999; }
        .chat #send-btn { background: #075e54; color: white; }

        .chat .msg-row { display: flex; margin-bottom: 8px; }
        .chat .msg-row.user { justify-content: flex-end; }
        .chat .msg-row.bot { justify-content: flex-start; }
        .chat .bubble {
            max-width: 85%; padding: 8px 12px; border-radius: 12px;
            font-size: 14px; line-height: 1.45; white-space: pre-wrap;
            word-wrap: break-word;
        }
        .chat .msg-row.user .bubble { background: #dcf8c6; border-bottom-right-radius: 4px; }
        .chat .msg-row.bot .bubble {
            background: white; border-bottom-left-radius: 4px;
            box-shadow: 0 1px 1px rgba(0,0,0,0.1);
        }
        .chat .msg-time { font-size: 11px; color: #999; margin-top: 2px; }
        .chat .msg-row.user .msg-time { text-align: right; }
        .chat .msg-row.bot .msg-time { text-align: left; }
        .chat .msg-row.loading .bubble { background: #f5f5f5; color: #888; font-style: italic; }
        .chat .msg-row.error .bubble { background: #ffe0e0; color: #c00; }
        .chat .avatar {
            width: 28px; height: 28px; border-radius: 50%; background: #075e54;
            color: white; display: flex; align-items: center; justify-content: center;
            font-size: 13px; font-weight: bold; margin-right: 8px; flex-shrink: 0;
            align-self: flex-end;
        }

        @media (max-width: 600px) { .chat .bubble { max-width: 90%; } }
        @media (min-width: 768px) { #output { max-width: 800px; margin: 0 auto; width: 100%; } }
    </style>
</head>
<body class="chat">
    <div id="header">
        <h1>FotMob</h1>
        <button id="mode-toggle" onclick="toggleMode()">Terminal</button>
    </div>
    <div id="output"></div>
    <div id="input-bar">
        <input type="text" id="query-input" placeholder="Ask about football..." autocomplete="off" autofocus>
        <button id="send-btn" onclick="sendQuery()">&#10148;</button>
    </div>
    <script>
        const O = document.getElementById('output');
        const I = document.getElementById('query-input');
        const B = document.getElementById('send-btn');
        const T = document.getElementById('mode-toggle');
        let M = localStorage.getItem('ui') || 'chat';

        function setMode(m) {
            M = m; document.body.className = m;
            T.textContent = m === 'chat' ? 'Terminal' : 'Chat';
            B.innerHTML = m === 'chat' ? '&#10148;' : 'Go';
            localStorage.setItem('ui', m);
        }
        function toggleMode() { setMode(M === 'chat' ? 'terminal' : 'chat'); }
        setMode(M);

        function now() { return new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}); }
        function esc(t) { return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\\n/g,'<br>'); }
        function scroll() { O.scrollTop = O.scrollHeight; }

        function add(who, text, cls) {
            if (M === 'chat') {
                const r = document.createElement('div');
                r.className = 'msg-row ' + who + (cls ? ' ' + cls : '');
                let inner = '';
                if (who === 'bot') inner += '<div class="avatar">F</div>';
                inner += '<div><div class="bubble">' + esc(text) + '</div><div class="msg-time">' + now() + '</div></div>';
                r.innerHTML = inner;
                O.appendChild(r);
            } else {
                const d = document.createElement('div');
                d.className = 'msg ' + who + (cls ? ' ' + cls : '');
                d.textContent = text;
                O.appendChild(d);
            }
            scroll();
        }

        function addLoading() {
            const id = 'L' + Date.now();
            if (M === 'chat') {
                const r = document.createElement('div');
                r.className = 'msg-row bot loading'; r.id = id;
                r.innerHTML = '<div class="avatar">F</div><div><div class="bubble">Thinking...</div></div>';
                O.appendChild(r);
            } else {
                const d = document.createElement('div');
                d.className = 'msg loading'; d.id = id; d.textContent = 'Processing...';
                O.appendChild(d);
            }
            scroll(); return id;
        }

        add('bot', 'Football data at your fingertips. Ask anything!\\nExamples: arsenal, standings pl, haaland stats');

        I.addEventListener('keydown', e => { if (e.key === 'Enter' && I.value.trim()) sendQuery(); });

        async function sendQuery() {
            const q = I.value.trim(); if (!q) return;
            add('user', q);
            const lid = addLoading();
            I.value = ''; B.disabled = true;
            try {
                const r = await fetch('/query', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({query:q})});
                const d = await r.json();
                document.getElementById(lid)?.remove();
                add('bot', d.response || d.error, d.error ? 'error' : '');
            } catch(e) {
                document.getElementById(lid)?.remove();
                add('bot', 'Network error: ' + e.message, 'error');
            }
            B.disabled = false; I.focus();
        }
    </script>
</body>
</html>"""


# ============================================================================
# ROUTES
# ============================================================================

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/query", methods=["POST"])
def query_endpoint():
    data = request.get_json()
    q = data.get("query", "").strip()
    if not q:
        return jsonify({"error": "Empty query"})
    try:
        response = handle_query(q)
        return jsonify({"response": response})
    except Exception as e:
        return jsonify({"error": str(e)})


# ============================================================================
# STARTUP
# ============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    is_cloud = os.environ.get("RENDER") or os.environ.get("PORT")

    if is_cloud:
        print(f"Starting FotMob Web CLI on port {port} (cloud mode)")
        app.run(host="0.0.0.0", port=port, debug=False)
    else:
        import subprocess, time

        print(f"\n  Starting FotMob Web CLI on port {port}...")
        print(f"  Local: http://localhost:{port}")
        print(f"\n  Starting ngrok tunnel...")

        try:
            subprocess.run(["taskkill", "/f", "/im", "ngrok.exe"],
                           capture_output=True, timeout=5)
        except Exception:
            pass

        ngrok_proc = subprocess.Popen(
            ["ngrok", "http", str(port), "--log=stdout"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        time.sleep(3)

        try:
            import urllib.request, json as _json
            resp = urllib.request.urlopen("http://localhost:4040/api/tunnels", timeout=5)
            tunnels = _json.loads(resp.read())
            public_url = tunnels["tunnels"][0]["public_url"]
            print(f"\n  ====================================")
            print(f"  PUBLIC URL: {public_url}")
            print(f"  ====================================")
            print(f"\n  Open this URL on your phone's Chrome!")
            print(f"  Press Ctrl+C to stop.\n")
        except Exception:
            print(f"  ngrok URL not ready. Check http://localhost:4040\n")

        try:
            app.run(host="0.0.0.0", port=port, debug=False)
        except KeyboardInterrupt:
            pass
        finally:
            ngrok_proc.terminate()
            print("\n  Server stopped.")
