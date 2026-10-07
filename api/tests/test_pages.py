async def test_privacy_page_is_served(client):
    resp = await client.get("/adatkezeles")
    assert resp.status_code == 200
    assert "90 napig" in resp.text


async def test_landing_links_to_the_privacy_page(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert 'href="/adatkezeles"' in resp.text
    assert 'id="privacy"' not in resp.text
