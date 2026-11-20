"""Flask route tests using a fake backend (no network required)."""

from uuid import uuid4

import pytest

from frontend import main as frontend


@pytest.fixture
def app_client(monkeypatch):
    books = {}
    calls = []

    def fake_api_request(method, path, **kwargs):
        calls.append((method, path))
        if method == "GET" and path == "/books":
            return list(books.values())
        if method == "GET" and path == "/stats":
            return {
                "total_titles": len(books),
                "total_copies": sum(b["quantity"] for b in books.values()),
                "inventory_value": "0.00",
                "low_stock_titles": sum(b["quantity"] <= 5 for b in books.values()),
            }
        if method == "GET" and path == "/health":
            return {"status": "healthy"}
        if method == "POST" and path == "/books":
            book = {**kwargs["json"], "id": str(uuid4())}
            book["quantity"] = int(book["quantity"])
            books[book["id"]] = book
            return book
        if path.startswith("/books/"):
            book_id = path.rsplit("/", 1)[1]
            if method == "PUT" and book_id in books:
                books[book_id].update(kwargs["json"])
                books[book_id]["quantity"] = int(books[book_id]["quantity"])
                return books[book_id]
            if method == "DELETE" and book_id in books:
                del books[book_id]
                return None
        raise AssertionError(f"Unexpected API call: {method} {path}")

    monkeypatch.setattr(frontend, "api_request", fake_api_request)
    frontend.app.config.update(TESTING=True, SECRET_KEY="test-key")
    return frontend.app.test_client(), books, calls


def csrf_token(client):
    client.get("/")
    with client.session_transaction() as session:
        return session["csrf_token"]


def sample_form(token):
    return {
        "csrf_token": token,
        "title": "The Maple Bookshop",
        "author": "A. Reader",
        "genre": "Fiction",
        "isbn": "9781234567890",
        "price": "24.50",
        "quantity": "8",
        "description": "A cozy story",
    }


def test_frontend_renders_and_links_stylesheet(app_client):
    client, _, _ = app_client
    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "AB BookHub" in html
    assert "Your book collection" in html
    assert "/static/styles.css" in html
    assert "/static/app.js" in html
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/health").json == {
        "status": "healthy",
        "api_connectivity": True,
    }


def test_create_edit_search_and_delete_via_flask_routes(app_client):
    client, books, calls = app_client
    token = csrf_token(client)
    form = sample_form(token)
    added = client.post("/books", data=form, follow_redirects=True)
    assert added.status_code == 200
    assert "Book added to your collection" in added.get_data(as_text=True)
    assert len(books) == 1
    book_id = next(iter(books))
    assert ("POST", "/books") in calls

    matched = client.get("/?q=Maple")
    assert "The Maple Bookshop" in matched.get_data(as_text=True)
    not_matched = client.get("/?q=other")
    assert "No books match your search" in not_matched.get_data(as_text=True)

    changed = {**form, "title": "The Evergreen Bookshop", "quantity": "2"}
    edited = client.post(f"/books/{book_id}/edit", data=changed, follow_redirects=True)
    assert edited.status_code == 200
    assert "Book details saved successfully" in edited.get_data(as_text=True)
    assert books[book_id]["title"] == "The Evergreen Bookshop"
    assert ("PUT", f"/books/{book_id}") in calls

    deleted = client.post(
        f"/books/{book_id}/delete", data={"csrf_token": token}, follow_redirects=True
    )
    assert deleted.status_code == 200
    assert "Book removed from your collection" in deleted.get_data(as_text=True)
    assert not books
    assert ("DELETE", f"/books/{book_id}") in calls


def test_csrf_is_required_for_modifications(app_client):
    client, books, _ = app_client
    token = csrf_token(client)
    assert client.post("/books", data=sample_form("wrong-token")).status_code == 400
    assert client.post("/books", data=sample_form(token)).status_code == 302
    book_id = next(iter(books))
    assert (
        client.post(f"/books/{book_id}/edit", data=sample_form("")).status_code == 400
    )
    assert client.post(f"/books/{book_id}/delete", data={}).status_code == 400
    assert book_id in books


def test_backend_unavailable_displays_error_and_health_503(app_client, monkeypatch):
    client, _, _ = app_client

    def down(*_args, **_kwargs):
        raise frontend.StoreAPIError("The bookstore API is unavailable.")

    monkeypatch.setattr(frontend, "api_request", down)
    response = client.get("/")
    assert response.status_code == 200
    assert "The bookstore API is unavailable." in response.get_data(as_text=True)
    assert client.get("/health").status_code == 503
