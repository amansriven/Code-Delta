from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()


class Item(BaseModel):
    name: str
    price: float
    discount: float  # regression: used to default to 0.0, now required


@app.post("/items", status_code=201)
def create_item(item: Item):
    return item


@app.get("/items/{item_id}")
def get_item(item_id: int):
    if item_id == 999:
        raise HTTPException(status_code=404, detail="item not found")
    return {"item_id": item_id}
