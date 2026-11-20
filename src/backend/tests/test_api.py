"""Isolated CRUD smoke/regression tests for the backend."""

import pytest
from backend.main import app
from fastapi.testclient import TestClient

from backend import storage


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "BOOKS_FILE", tmp_path / "books.csv")
    return TestClient(app)


@pytest.fixture
def sample_book():
    return {
        "title": "  The Paper Garden  ",
        "author": "C. Bloom",
        "genre": "Fiction",
        "isbn": "9781234567890",
        "price": "18.99",
        "quantity": 7,
        "description": "A novel about second chances.",
    }


def test_crud_and_stats(client, sample_book):
    assert client.get("/books").json() == []
    resp = client.post("/books", json=sample_book)
    assert resp.status_code == 201, resp.text
    book = resp.json()
    assert book["title"] == "The Paper Garden"
    book_id = book["id"]
    assert client.get(f"/books/{book_id}").json()["id"] == book_id
    assert len(client.get("/books", params={"q": "garden"}).json()) == 1
    assert len(client.get("/books", params={"genre": "FICTION"}).json()) == 1
    assert client.get("/books", params={"q": "unrelated"}).json() == []
    assert client.get("/stats").json() == {
        "total_titles": 1,
        "total_copies": 7,
        "inventory_value": "132.93",
        "low_stock_titles": 0,
    }
    changed = {**sample_book, "title": "Paper Garden: Revised", "quantity": 2}
    edited = client.put(f"/books/{book_id}", json=changed)
    assert edited.status_code == 200
    assert edited.json()["title"] == changed["title"]
    assert edited.json()["created_at"] == book["created_at"]
    assert edited.json()["updated_at"] >= book["updated_at"]
    assert client.get("/stats").json()["low_stock_titles"] == 1
    assert client.delete(f"/books/{book_id}").status_code == 204
    assert client.get("/books").json() == []
    assert client.get(f"/books/{book_id}").status_code == 404
    assert client.put(f"/books/{book_id}", json=changed).status_code == 404
    assert client.delete(f"/books/{book_id}").status_code == 404


def test_rejects_invalid_fields(client, sample_book):
    for mutation in (
        {"title": "   "},
        {"price": "-1"},
        {"quantity": -2},
        {"price": "5.999"},
        {"author": ""},
        {"quantity": "abc"},
    ):
        assert (
            client.post("/books", json={**sample_book, **mutation}).status_code == 422
        )
    assert client.get("/books").json() == []


def test_csv_persists_and_preserves_unicode(client, sample_book):
    sample_book["title"] = 'Café, Books & "Beyond"'
    created = client.post("/books", json=sample_book).json()
    assert storage.BOOKS_FILE.exists()
    assert client.get(f"/books/{created['id']}").json()["title"] == sample_book["title"]
