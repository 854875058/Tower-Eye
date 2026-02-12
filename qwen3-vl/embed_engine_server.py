import os
import io
import base64
from fastapi import FastAPI, Body
from pydantic import BaseModel
from typing import List, Optional
from vllm import LLM, EngineArgs
from PIL import Image
import uvicorn

os.environ["CUDA_VISIBLE_DEVICES"] = "2,3"
app = FastAPI()

# 初始化引擎
e_args = EngineArgs(
    model="./models/qwen/Qwen3-VL-Embedding-8B",
    runner="pooling",
    tensor_parallel_size=2,
    trust_remote_code=True,
    gpu_memory_utilization=0.8,
    enforce_eager=True,
    max_model_len=4096
)
engine = LLM(**vars(e_args))


def _build_request(text: str, image_path: str = None, image_base64: str = None) -> dict:
    prompt = f"User: <|vision_start|><|image_pad|><|vision_end|>{text}\nAssistant: "
    if image_base64:
        img = Image.open(io.BytesIO(base64.b64decode(image_base64))).convert("RGB")
    elif image_path:
        img = Image.open(image_path).convert("RGB")
    else:
        raise ValueError("必须提供 image_path 或 image_base64")
    return {"prompt": prompt, "multi_modal_data": {"image": img}}


@app.post("/v1/tower/embed")
async def get_embedding(text: str = Body(""), image_path: str = Body(None), image_base64: str = Body(None)):
    try:
        req = _build_request(text, image_path=image_path, image_base64=image_base64)
        outputs = engine.embed([req])
        return {"embedding": outputs[0].outputs.embedding}
    except Exception as e:
        return {"error": str(e)}


class BatchItem(BaseModel):
    text: str = ""
    image_path: Optional[str] = None
    image_base64: Optional[str] = None


class BatchRequest(BaseModel):
    items: List[BatchItem]


@app.post("/v1/tower/embed_batch")
async def get_embedding_batch(req: BatchRequest):
    """批量向量化 — 一次调用处理多张图片，利用 vLLM 内部批处理加速"""
    try:
        requests = [_build_request(item.text, image_path=item.image_path, image_base64=item.image_base64) for item in req.items]
        outputs = engine.embed(requests)
        embeddings = [out.outputs.embedding for out in outputs]
        return {"embeddings": embeddings}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8010)
