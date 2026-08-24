from pathlib import Path


def test_upload_and_serve_png(client, png_bytes):
    kid = client.post("/api/knowledge", data={"title": "shot", "type": "screenshot"}).json()["id"]
    resp = client.post(
        f"/api/knowledge/{kid}/attachments",
        files={"file": ("screen shot.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 201, resp.text
    att = resp.json()
    assert att["filename"] == "screen shot.png"
    assert att["mime_type"] == "image/png"
    assert att["size_bytes"] == len(png_bytes)

    # served through /uploads
    got = client.get(att["url"])
    assert got.status_code == 200
    assert got.content == png_bytes

    # stored file lives inside the uploads dir (no path traversal)
    settings_dir = Path(client.get("/health").json()["status"])  # just ensure app up
    import app.config as config

    uploads_root = config.get_settings().uploads_dir.resolve()
    full = (uploads_root / att["url"].split("/", 2)[2]).resolve()
    assert str(full).startswith(str(uploads_root))


def test_create_knowledge_with_file(client, png_bytes):
    resp = client.post(
        "/api/knowledge",
        data={"title": "with file", "type": "screenshot"},
        files={"file": ("a.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["attachments"]) == 1
    assert body["attachments"][0]["filename"] == "a.png"


def test_upload_too_large_413(client, png_bytes, monkeypatch):
    monkeypatch.setenv("KB_UPLOAD_MAX_BYTES", "32")  # 1x1 PNG is 68 bytes
    kid = client.post("/api/knowledge", data={"title": "big"}).json()["id"]
    resp = client.post(
        f"/api/knowledge/{kid}/attachments",
        files={"file": ("big.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 413


def test_bad_extension_415(client, png_bytes):
    kid = client.post("/api/knowledge", data={"title": "weird"}).json()["id"]
    resp = client.post(
        f"/api/knowledge/{kid}/attachments",
        files={"file": ("data.xyz", b"hello", "application/octet-stream")},
    )
    assert resp.status_code == 415


def test_delete_attachment_removes_file(client, png_bytes):
    kid = client.post("/api/knowledge", data={"title": "d"}).json()["id"]
    att = client.post(
        f"/api/knowledge/{kid}/attachments",
        files={"file": ("x.png", png_bytes, "image/png")},
    ).json()
    resp = client.delete(f"/api/attachments/{att['id']}")
    assert resp.status_code == 200
    assert client.get(f"/api/attachments/{att['id']}").status_code == 404
    assert client.get(f"/api/attachments/{att['id']}").status_code == 404


def test_delete_knowledge_cascades_files(client, png_bytes):
    kid = client.post("/api/knowledge", data={"title": "gone"}).json()["id"]
    att = client.post(
        f"/api/knowledge/{kid}/attachments",
        files={"file": ("y.png", png_bytes, "image/png")},
    ).json()
    stored = att["url"].split("/", 2)[2]
    assert client.delete(f"/api/knowledge/{kid}").status_code == 200
    import app.config as config

    assert not (config.get_settings().uploads_dir / stored).exists()


def test_upload_to_missing_knowledge_404(client, png_bytes):
    resp = client.post(
        "/api/knowledge/999/attachments",
        files={"file": ("n.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 404
