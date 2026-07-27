from fastapi import FastAPI, HTTPException
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
    if item_id < 0:
        raise HTTPException(status_code=404, detail="item not found")
    return {"item_id": item_id}


@app.get("/items")
def list_items(limit: int = 10):
    return {"limit": limit}
