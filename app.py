"""VPS Visual — navegador visual de VPS que mostra os comandos equivalentes."""
import os, json, time, threading, uuid, re
from pathlib import Path
from flask import Flask, render_template, request, jsonify, session
import paramiko

# Load .env file if exists
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())

# In-memory session store: sid -> { client, cwd, host, user }
sessions = {}
sessions_lock = threading.Lock()

# Unique end-marker to detect when command output finishes
MARKER = "___VPS_VISUAL_END___"


def get_sess():
    """Get persistent SSH session from flask session id."""
    sid = session.get("sid")
    if sid:
        with sessions_lock:
            return sessions.get(sid)
    return None


def ssh_exec(cmd, timeout=15):
    """Execute command in persistent SSH connection, preserving cwd."""
    sess = get_sess()
    if not sess:
        raise ConnectionError("Nao conectado")

    client = sess["client"]
    cwd = sess["cwd"]

    # Wrap command so it runs in the current working directory and reports
    # the new cwd afterwards (so cd works across calls)
    wrapped = (
        f'cd {cwd} 2>/dev/null; {cmd}\n'
        f'__exit_code=$?\n'
        f'echo ""\n'
        f'echo "{MARKER}_EXIT_${{__exit_code}}"\n'
        f'echo "{MARKER}_CWD_$(pwd)"\n'
    )

    stdin, stdout, stderr = client.exec_command(wrapped, timeout=timeout)
    raw_out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")

    # Parse exit code and new cwd from output
    exit_code = 0
    new_cwd = cwd
    clean_lines = []
    for line in raw_out.split("\n"):
        if f"{MARKER}_EXIT_" in line:
            try:
                exit_code = int(line.split(f"{MARKER}_EXIT_")[1].strip())
            except (ValueError, IndexError):
                pass
        elif f"{MARKER}_CWD_" in line:
            parsed = line.split(f"{MARKER}_CWD_")[1].strip()
            if parsed:
                new_cwd = parsed
        else:
            clean_lines.append(line)

    # Update stored cwd
    sess["cwd"] = new_cwd

    out = "\n".join(clean_lines)
    # Remove trailing blank lines from our echo
    out = out.rstrip("\n") + "\n" if out.strip() else ""

    return out, err, exit_code


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/connect", methods=["POST"])
def api_connect():
    host = request.json.get("host", "").strip()
    user = request.json.get("user", "root").strip()
    password = request.json.get("password", "")
    port = int(request.json.get("port", 22))

    if not host:
        return jsonify({"success": False, "error": "Host vazio"})

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, port=port, username=user, password=password, timeout=10)
        stdin, stdout, stderr = client.exec_command("hostname && uname -a", timeout=10)
        info = stdout.read().decode("utf-8", errors="replace").strip()
        # Get initial home directory
        stdin2, stdout2, stderr2 = client.exec_command("pwd", timeout=5)
        home = stdout2.read().decode("utf-8", errors="replace").strip() or "/root"
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

    # Store persistent connection
    sid = str(uuid.uuid4())
    session["sid"] = sid
    with sessions_lock:
        sessions[sid] = {
            "client": client,
            "host": host,
            "user": user,
            "cwd": home,
        }

    return jsonify({
        "success": True,
        "info": info,
        "host": host,
        "user": user,
    })


@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    sid = session.get("sid")
    if sid:
        with sessions_lock:
            sess = sessions.pop(sid, None)
            if sess and sess.get("client"):
                try:
                    sess["client"].close()
                except Exception:
                    pass
    session.pop("sid", None)
    return jsonify({"success": True})


@app.route("/api/status", methods=["POST"])
def api_status():
    sess = get_sess()
    if sess:
        # Verify connection is still alive
        try:
            transport = sess["client"].get_transport()
            if transport and transport.is_active():
                return jsonify({"connected": True, "host": sess["host"], "user": sess["user"]})
        except Exception:
            pass
        # Dead connection — clean up
        with sessions_lock:
            sessions.pop(session.get("sid"), None)
        session.pop("sid", None)
    return jsonify({"connected": False})


@app.route("/api/ls", methods=["POST"])
def api_ls():
    if not get_sess():
        return jsonify({"error": "Nao conectado", "items": []})
    path = request.json.get("path", "/")
    path = path.replace(";", "").replace("&&", "").replace("|", "").replace("`", "")
    cmd = f'ls -la --time-style=long-iso "{path}" 2>&1'
    out, err, code = ssh_exec(cmd)

    items = []
    for line in out.strip().split("\n")[1:]:
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        perms, links, owner, group, size, date, hour, name = parts
        if " -> " in name:
            name = name.split(" -> ")[0]
        if name in (".", ".."):
            continue
        items.append({
            "name": name,
            "perms": perms,
            "owner": owner,
            "group": group,
            "size": int(size) if size.isdigit() else 0,
            "date": f"{date} {hour}",
            "is_dir": perms.startswith("d"),
            "is_link": perms.startswith("l"),
        })

    return jsonify({
        "command": f"ls -la {path}",
        "path": path,
        "items": items,
        "error": err if code != 0 else None,
    })


@app.route("/api/cat", methods=["POST"])
def api_cat():
    if not get_sess():
        return jsonify({"error": "Nao conectado"})
    path = request.json.get("path", "")
    path = path.replace(";", "").replace("&&", "").replace("|", "").replace("`", "")
    max_lines = request.json.get("max_lines", 200)

    cmd = f'head -n {max_lines} "{path}" 2>&1'
    out, err, code = ssh_exec(cmd)

    return jsonify({
        "command": f"cat {path}" if max_lines >= 200 else f"head -n {max_lines} {path}",
        "content": out,
        "error": err if code != 0 else None,
    })


@app.route("/api/tail", methods=["POST"])
def api_tail():
    if not get_sess():
        return jsonify({"error": "Nao conectado"})
    path = request.json.get("path", "")
    path = path.replace(";", "").replace("&&", "").replace("|", "").replace("`", "")
    lines = request.json.get("lines", 50)

    cmd = f'tail -n {lines} "{path}" 2>&1'
    out, err, code = ssh_exec(cmd)

    return jsonify({
        "command": f"tail -n {lines} {path}",
        "content": out,
        "error": err if code != 0 else None,
    })


@app.route("/api/mkdir", methods=["POST"])
def api_mkdir():
    if not get_sess():
        return jsonify({"error": "Nao conectado"})
    path = request.json.get("path", "")
    path = path.replace(";", "").replace("&&", "").replace("|", "").replace("`", "")

    cmd = f'mkdir -p "{path}" 2>&1'
    out, err, code = ssh_exec(cmd)

    return jsonify({
        "command": f"mkdir -p {path}",
        "success": code == 0,
        "error": (out + err).strip() if code != 0 else None,
    })


@app.route("/api/rm", methods=["POST"])
def api_rm():
    if not get_sess():
        return jsonify({"error": "Nao conectado"})
    path = request.json.get("path", "")
    path = path.replace(";", "").replace("&&", "").replace("|", "").replace("`", "")
    is_dir = request.json.get("is_dir", False)

    if is_dir:
        cmd = f'rm -rf "{path}" 2>&1'
        shown = f"rm -rf {path}"
    else:
        cmd = f'rm "{path}" 2>&1'
        shown = f"rm {path}"

    out, err, code = ssh_exec(cmd)

    return jsonify({
        "command": shown,
        "success": code == 0,
        "error": (out + err).strip() if code != 0 else None,
    })


@app.route("/api/mv", methods=["POST"])
def api_mv():
    if not get_sess():
        return jsonify({"error": "Nao conectado"})
    src = request.json.get("src", "")
    dst = request.json.get("dst", "")
    for ch in [";", "&&", "|", "`"]:
        src = src.replace(ch, "")
        dst = dst.replace(ch, "")

    cmd = f'mv "{src}" "{dst}" 2>&1'
    out, err, code = ssh_exec(cmd)

    return jsonify({
        "command": f"mv {src} {dst}",
        "success": code == 0,
        "error": (out + err).strip() if code != 0 else None,
    })


@app.route("/api/write", methods=["POST"])
def api_write():
    sess = get_sess()
    if not sess:
        return jsonify({"error": "Nao conectado"})
    path = request.json.get("path", "")
    content = request.json.get("content", "")
    path = path.replace(";", "").replace("&&", "").replace("|", "").replace("`", "")

    sftp = sess["client"].open_sftp()
    with sftp.file(path, "w") as f:
        f.write(content)
    sftp.close()

    return jsonify({
        "command": f"nano {path}",
        "success": True,
    })


@app.route("/api/exec", methods=["POST"])
def api_exec():
    sess = get_sess()
    if not sess:
        return jsonify({"error": "Nao conectado"})
    cmd = request.json.get("command", "")
    timeout = request.json.get("timeout", 15)
    out, err, code = ssh_exec(cmd, timeout=min(timeout, 30))

    return jsonify({
        "command": cmd,
        "stdout": out,
        "stderr": err,
        "exit_code": code,
        "cwd": sess["cwd"],
    })


@app.route("/api/info", methods=["POST"])
def api_info():
    if not get_sess():
        return jsonify({"error": "Nao conectado"})
    path = request.json.get("path", "")
    path = path.replace(";", "").replace("&&", "").replace("|", "").replace("`", "")

    cmd = f'stat "{path}" 2>&1 && echo "---FILE_CMD---" && file "{path}" 2>&1'
    out, err, code = ssh_exec(cmd)

    return jsonify({
        "command": f"stat {path}",
        "content": out,
        "error": err if code != 0 else None,
    })


@app.route("/api/disk", methods=["POST"])
def api_disk():
    if not get_sess():
        return jsonify({"error": "Nao conectado"})
    out, err, code = ssh_exec("df -h / && echo '---' && free -h")
    return jsonify({
        "command": "df -h / && free -h",
        "content": out,
    })


@app.route("/api/docker/ps", methods=["POST"])
def api_docker_ps():
    if not get_sess():
        return jsonify({"error": "Nao conectado"})
    cmd = 'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"'
    out, err, code = ssh_exec(cmd)
    return jsonify({
        "command": "docker ps",
        "content": out,
        "error": err if code != 0 else None,
    })


@app.route("/api/docker/logs", methods=["POST"])
def api_docker_logs():
    if not get_sess():
        return jsonify({"error": "Nao conectado"})
    name = request.json.get("name", "")
    name = name.replace(";", "").replace("&&", "").replace("|", "").replace("`", "")
    lines = request.json.get("lines", 50)

    cmd = f"docker logs --tail {lines} {name} 2>&1"
    out, err, code = ssh_exec(cmd)

    return jsonify({
        "command": f"docker logs --tail {lines} {name}",
        "content": out,
    })


@app.route("/api/services", methods=["POST"])
def api_services():
    if not get_sess():
        return jsonify({"error": "Nao conectado"})
    cmd = "systemctl list-units --type=service --state=running --no-pager --no-legend"
    out, err, code = ssh_exec(cmd)
    return jsonify({
        "command": "systemctl list-units --type=service --state=running",
        "content": out,
    })


if __name__ == "__main__":
    print("VPS Visual rodando em http://localhost:5000")
    app.run(debug=True, port=5000)
