import os
from fastapi import FastAPI, Body
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

@app.post("/v1/tower/embed")
async def get_embedding(text: str = Body(""), image_path: str = Body(...)):
    try:
        prompt = f"User: <|vision_start|><|image_pad|><|vision_end|>{text}\nAssistant: "
        img = Image.open(image_path).convert("RGB")
        outputs = engine.embed([{"prompt": prompt, "multi_modal_data": {"image": img}}])
        return {"embedding": outputs[0].outputs.embedding}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8010)
