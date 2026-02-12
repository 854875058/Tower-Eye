import os
from fastapi import FastAPI, Body
from vllm import LLM, EngineArgs
from PIL import Image
import uvicorn

os.environ["CUDA_VISIBLE_DEVICES"] = "4,5"
app = FastAPI()

r_args = EngineArgs(
    model="./models/qwen/Qwen3-VL-Reranker-8B",
    runner="pooling",
    tensor_parallel_size=2,
    trust_remote_code=True,
    gpu_memory_utilization=0.8,
    enforce_eager=True,
    max_model_len=4096,
    # 核心：只保留这一个关键参数，避开校验 Bug
    hf_overrides={"is_original_qwen3_reranker": True}
)
engine = LLM(**vars(r_args))

@app.post("/v1/tower/rerank")
async def get_rerank(text: str = Body(...), image_path: str = Body(...)):
    try:
        prompt = f"User: <|vision_start|><|image_pad|><|vision_end|>{text}\nAssistant: "
        img = Image.open(image_path).convert("RGB")
        # Reranker 在 pooling 模式下输出的通常是分类 logits 的第一个值作为 score
        outputs = engine.embed([{"prompt": prompt, "multi_modal_data": {"image": img}}])
        return {"score": outputs[0].outputs.embedding[0]}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8011)
