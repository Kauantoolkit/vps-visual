"""VPS Visual — navegador visual de VPS que mostra os comandos equivalentes."""
import os, json, time
from pathlib import Path
from flask import Flask, render_template, request, jsonify
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

# Configuração da VPS — defina via variáveis de ambiente ou .env
VPS_HOST = os.environ.get("VPS_HOST", "")
VPS_USER = os.environ.get("VPS_USER", "root")
VPS_PASS = os.environ.get("VPS_PASS", "")
VPS_PORT = int(os.environ.get("VPS_PORT", "22"))


def ssh_exec(cmd, timeout=15):
    """Executa um comando na VPS e retorna (stdout, stderr, exit_code)."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=10)
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    client.close()
    return out, err, code


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/ls", methods=["POST"])
def api_ls():
    path = request.json.get("path", "/")
    # Sanitize
    path = path.replace(";", "").replace("&&", "").replace("|", "").replace("`", "")
    cmd = f'ls -la --time-style=long-iso "{path}" 2>&1'
    out, err, code = ssh_exec(cmd)

    items = []
    for line in out.strip().split("\n")[1:]:  # skip "total X"
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        perms, links, owner, group, size, date, hour, name = parts
        # Symlinks: "bin -> usr/bin" — keep only the link name
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
    path = request.json.get("path", "")
    content = request.json.get("content", "")
    path = path.replace(";", "").replace("&&", "").replace("|", "").replace("`", "")

    # Upload via SFTP
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=10)
    sftp = client.open_sftp()
    with sftp.file(path, "w") as f:
        f.write(content)
    sftp.close()
    client.close()

    return jsonify({
        "command": f"nano {path}",
        "success": True,
    })


@app.route("/api/exec", methods=["POST"])
def api_exec():
    cmd = request.json.get("command", "")
    timeout = request.json.get("timeout", 15)
    out, err, code = ssh_exec(cmd, timeout=min(timeout, 30))

    return jsonify({
        "command": cmd,
        "stdout": out,
        "stderr": err,
        "exit_code": code,
    })


@app.route("/api/info", methods=["POST"])
def api_info():
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
    out, err, code = ssh_exec("df -h / && echo '---' && free -h")
    return jsonify({
        "command": "df -h / && free -h",
        "content": out,
    })


@app.route("/api/docker/ps", methods=["POST"])
def api_docker_ps():
    cmd = 'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"'
    out, err, code = ssh_exec(cmd)
    return jsonify({
        "command": "docker ps",
        "content": out,
        "error": err if code != 0 else None,
    })


@app.route("/api/docker/logs", methods=["POST"])
def api_docker_logs():
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
    cmd = "systemctl list-units --type=service --state=running --no-pager --no-legend"
    out, err, code = ssh_exec(cmd)
    return jsonify({
        "command": "systemctl list-units --type=service --state=running",
        "content": out,
    })


if __name__ == "__main__":
    print("VPS Visual rodando em http://localhost:5000")
    print(f"Conectando em {VPS_USER}@{VPS_HOST}:{VPS_PORT}")
    app.run(debug=True, port=5000)
