from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class Item(BaseModel):
    name: str
    price: float
    discount: float = 0.0


@app.post("/items", status_code=201)
def create_item(item: Item):
    return item


@app.get("/items/{item_id}")
def get_item(item_id: int):
    # regression: dropped the 404-for-unknown-id check, always returns 200
    return {"item_id": item_id}
