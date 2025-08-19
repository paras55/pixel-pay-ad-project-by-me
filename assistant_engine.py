import json
import time
import base64
from typing import List, Tuple, Dict, Any, Optional
from io import BytesIO
import streamlit as st

from openai import OpenAI

# Hard-coded credentials and IDs per user requirement
API_KEY = st.secrets["OpenAI_key"]
ANALYSIS_ASSISTANT_ID = st.secrets["Assistant_secret"]


def _extract_json_blocks(text: str) -> List[dict]:
    blocks: List[str] = []
    cur: List[str] = []
    in_json = False
    for line in text.splitlines():
        if line.strip().startswith("```") and "json" in line.lower():
            in_json = True
            cur = []
            continue
        if line.strip().startswith("```") and in_json:
            in_json = False
            if cur:
                blocks.append("\n".join(cur))
            cur = []
            continue
        if in_json:
            cur.append(line)

    if not blocks and text.strip().startswith("{"):
        try:
            json.loads(text)
            blocks.append(text)
        except Exception:
            pass

    parsed: List[dict] = []
    for b in blocks:
        try:
            parsed.append(json.loads(b))
        except Exception:
            pass
    return parsed


def analyze_images(api_key: Optional[str], assistant_id: Optional[str], images: List[Tuple[str, bytes]]) -> Tuple[dict, dict]:
    """
    Analyze images with an OpenAI Assistant and return two JSON objects:
    - base prompt JSON (spec)
    - variants JSON

    IMPORTANT: Sends ONLY images to the assistant (no text message),
    per requirement. `images` is a list of (name_or_id, image_bytes).
    """
    api_key = api_key or API_KEY
    assistant_id = assistant_id or ANALYSIS_ASSISTANT_ID
    client = OpenAI(api_key=api_key)

    file_ids: List[str] = []
    for name, data in images:
        file = BytesIO(data)
        file.name = f"{name}.png" if not hasattr(file, "name") else file.name
        fr = client.files.create(file=file, purpose="vision")
        file_ids.append(fr.id)

    thread = client.beta.threads.create()
    # Per requirement: send only images (no text instruction)
    content: List[Dict[str, Any]] = []
    for fid in file_ids:
        content.append({"type": "image_file", "image_file": {"file_id": fid, "detail": "high"}})

    client.beta.threads.messages.create(thread_id=thread.id, role="user", content=content)
    run = client.beta.threads.runs.create(thread_id=thread.id, assistant_id=assistant_id)

    while run.status in ("queued", "in_progress", "cancelling"):
        time.sleep(1)
        run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)

    if run.status != "completed":
        raise RuntimeError(f"Assistant run failed: {run.status}")

    msgs = client.beta.threads.messages.list(thread_id=thread.id)
    raw: Optional[str] = None
    for m in msgs.data:
        if m.role == "assistant":
            # take first text item
            for part in m.content:
                if part.type == "text":
                    raw = part.text.value
                    break
        if raw:
            break
    if not raw:
        raise RuntimeError("No assistant response found")

    blocks = _extract_json_blocks(raw)
    if len(blocks) < 2:
        raise RuntimeError("Could not parse two JSON blocks from assistant output")

    return blocks[0], blocks[1]


def generate_single_variant_image(api_key: Optional[str], base_prompt_json: dict, variant_json: dict, *, size: str = "1024x1024") -> bytes:
    """Generate one image using gpt-image-1 from a base JSON and one variant block."""
    api_key = api_key or API_KEY
    client = OpenAI(api_key=api_key)

    prompt_copy = json.loads(json.dumps(base_prompt_json))
    if isinstance(prompt_copy, dict):
        if "instructions" in prompt_copy and isinstance(prompt_copy["instructions"], dict):
            prompt_copy["instructions"]["variants"] = [variant_json]
        else:
            prompt_copy["variants"] = [variant_json]

    prompt_text = json.dumps(prompt_copy, ensure_ascii=False)

    img_resp = client.images.generate(
        model="gpt-image-1",
        prompt=prompt_text,
        size=size,
        n=1,
    )
    b64_img = img_resp.data[0].b64_json
    return base64.b64decode(b64_img)


def build_prompt_text(base_prompt_json: dict, variant_json: dict) -> str:
    """Return the exact JSON text we send to gpt-image-1 for a given variant."""
    prompt_copy = json.loads(json.dumps(base_prompt_json))
    if isinstance(prompt_copy, dict):
        if "instructions" in prompt_copy and isinstance(prompt_copy["instructions"], dict):
            prompt_copy["instructions"]["variants"] = [variant_json]
        else:
            prompt_copy["variants"] = [variant_json]
    return json.dumps(prompt_copy, ensure_ascii=False, indent=2)


