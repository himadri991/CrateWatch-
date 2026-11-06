CRATES = [
    {
        "id": "CW-01",
        "artwork": "Ochre Study",
        "artist": "Demo collection",
        "medium": "Oil on canvas",
        "crate": "Climate crate A",
    },
    {
        "id": "CW-02",
        "artwork": "Monsoon Letters",
        "artist": "Demo collection",
        "medium": "Ink on paper",
        "crate": "Flat crate B",
    },
    {
        "id": "CW-03",
        "artwork": "Blue Courtyard",
        "artist": "Demo collection",
        "medium": "Acrylic on canvas",
        "crate": "Climate crate C",
    },
    {
        "id": "CW-04",
        "artwork": "River Archive",
        "artist": "Demo collection",
        "medium": "Photographic print",
        "crate": "Flat crate D",
    },
    {
        "id": "CW-05",
        "artwork": "Cartographer's Table",
        "artist": "Demo collection",
        "medium": "Mixed media",
        "crate": "Climate crate E",
    },
    {
        "id": "CW-06",
        "artwork": "Evening Rag",
        "artist": "Demo collection",
        "medium": "Textile",
        "crate": "Textile crate F",
    },
]

CRATE_INDEX = {item["id"]: item for item in CRATES}

SHIPMENT = {
    "id": "SHP-2026-11-07-01",
    "origin": "National Gallery, New Delhi",
    "destination": "Harbour Museum, Mumbai",
    "carrier": "CrateWatch Demo Logistics",
    "departed": "2026-11-07T06:30:00Z",
    "expected_arrival": "2026-11-08T18:00:00Z",
}
