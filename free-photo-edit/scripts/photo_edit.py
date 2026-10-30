#!/usr/bin/env python3
"""Portable photo-edit ledger, bounded image API calls and deterministic delivery."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone


class WorkflowError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise WorkflowError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def no_links(path):
    """Reject symlinks and Windows junction/reparse points, including parents."""
    path = Path(path).absolute()
    for part in (path,) + tuple(path.parents):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            require(not part.is_symlink() and not (getattr(info, "st_file_attributes", 0) & 0x400),
                    "Symlink/junction paths are not allowed for task writes or cleanup.")
    return path.resolve()


def slug(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value)
            and len(value) <= 64, "IDs must use lowercase letters, numbers and single hyphens (max 64).")
    return value


def positive(value):
    return type(value) is int and value > 0


def validate_plan(plan):
    require(isinstance(plan, dict), "Plan must be a JSON object.")
    allowed = {"inputs", "preservation", "final_size", "bottom_padding_px", "max_generations", "variants"}
    require(set(plan) <= allowed, "Unknown plan fields; keep credentials and runtime configuration outside the plan.")
    require(plan.get("preservation") in ("pixel", "visual"), "preservation must be pixel or visual.")
    size = plan.get("final_size")
    require(isinstance(size, list) and len(size) == 2 and all(positive(v) for v in size),
            "final_size must contain two positive integer dimensions.")
    padding = plan.get("bottom_padding_px")
    require(type(padding) is int and padding >= 0, "bottom_padding_px must be a nonnegative integer.")
    variants = plan.get("variants")
    require(isinstance(variants, list) and variants, "At least one variant is required.")
    ids = []
    for variant in variants:
        require(isinstance(variant, dict) and set(variant) == {"id", "requirement", "count"},
                "Each variant needs exactly id, requirement, count.")
        ids.append(slug(variant["id"]))
        require(positive(variant["count"]) and isinstance(variant["requirement"], str)
                and variant["requirement"].strip(), "Each variant needs a positive count and requirement.")
    require(len(ids) == len(set(ids)), "Variant IDs must be unique.")
    require(type(plan.get("max_generations")) is int and
            plan["max_generations"] >= sum(v["count"] for v in variants),
            "max_generations must cover the planned initial image count.")
    require(isinstance(plan.get("inputs"), list) and plan["inputs"], "Declare at least one input file.")


def check_task(path):
    path = no_links(path)
    state = load_json(path)
    require(state.get("schema") == 1 and Path(state["work_dir"]).resolve() == path.parent,
            "Task location/schema mismatch.")
    require((path.parent / ".free-photo-edit-task").read_text(encoding="utf-8") == state["marker"],
            "Task ownership marker mismatch.")
    require(json_hash(state["plan"]) == state["plan_hash"], "Plan changed; confirm a revised plan instead of editing approved limits.")
    return path, state


@contextmanager
def task_lock(path):
    path = no_links(path)
    lock = path.with_name(path.name + ".lock")
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError:
        raise WorkflowError("Task is busy. Check the running command; retry after it finishes. Never delete an active lock.")
    try:
        handle.write(str(os.getpid()))
        handle.close()
        path, state = check_task(path)
        yield state
        save_json(path, state)
    finally:
        if not handle.closed:
            handle.close()
        lock.unlink(missing_ok=True)


def variant_for(state, variant):
    result = next((v for v in state["plan"]["variants"] if v["id"] == variant), None)
    require(result is not None, "Unknown variant.")
    return result


def attempt_for(state, attempt):
    result = next((a for a in state["attempts"] if a["id"] == attempt), None)
    require(result is not None, "Unknown attempt.")
    return result


def owned_temp(state, path):
    path = no_links(path)
    scratch = no_links(Path(state["work_dir"]) / "scratch")
    require(path != scratch and inside(path, scratch), "Temporary files must be inside this task's scratch directory.")
    require(str(path) not in {item["path"] for item in state["inputs"]}, "Input files cannot be tracked as disposable.")
    require(path.is_file(), "Temporary file does not exist.")
    return path


def track_file(state, path):
    path = owned_temp(state, path)
    state["temporary"][str(path)] = digest(path)


def pillow():
    try:
        from PIL import Image, ImageChops, ImageOps
    except ImportError:
        raise WorkflowError("Pillow missing. Use this interpreter's python -m pip install Pillow.")
    return Image, ImageChops, ImageOps


def read_image(path):
    Image, _, ImageOps = pillow()
    with Image.open(path) as image:
        image.load()
        return ImageOps.exif_transpose(image).convert("RGBA")


def save_png(image, path):
    path = no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        image.save(stream, format="PNG")


def inspect_canvas(image, width, height, bottom):
    require(positive(width) and positive(height) and type(bottom) is int and bottom >= 0,
            "Invalid crop dimensions.")
    expected = (width, height + bottom)
    issues = []
    if image.size != expected:
        issues.append("missing-bottom-padding" if bottom and image.size == (width, height) else "wrong-canvas-size")
    white_ratio = None
    if bottom and image.size == expected:
        band = image.crop((0, height, width, height + bottom))
        white = sum(1 for r, g, b, a in band.getdata() if min(r, g, b, a) >= 245)
        white_ratio = white / (width * bottom)
        if white_ratio < 0.90:
            issues.append("missing-bottom-padding")
    return {"valid": not issues, "issues": issues, "expected_size": list(expected),
            "actual_size": list(image.size), "bottom_white_ratio": white_ratio}


def cropped(image, width, height, bottom):
    validation = inspect_canvas(image, width, height, bottom)
    require(validation["valid"], "Canvas/bottom-band validation failed: " + ", ".join(validation["issues"]) +
            ". Do not crop scene content or append a band after generation.")
    return image.crop((0, 0, width, height)), validation["bottom_white_ratio"]


def build_prompt(state, variant, prompt):
    width, height = state["plan"]["final_size"]
    bottom = state["plan"]["bottom_padding_px"]
    requirement = variant_for(state, variant)["requirement"]
    layout = (f"Required output canvas: {width} x {height + bottom} pixels. "
              f"Content area: the TOP {width} x {height} pixels, rows 0 through {height - 1}. "
              f"Variant requirement: {requirement}.")
    if bottom:
        layout += (f"\nMANDATORY BOTTOM PADDING: the lowest {bottom} pixels, rows {height} through "
                   f"{height + bottom - 1}, must be a flat, opaque pure-white (#FFFFFF) horizontal strip "
                   "spanning the FULL width, with a straight horizontal boundary. "
                   "The white strip is outside the photograph and is part of this output canvas. "
                   "Do not extend the floor, background, textures or scene into this strip. "
                   "Keep the entire requested scene, all subjects, feet, chair legs and necessary shadows "
                   "inside the TOP content area. Do not shrink, stretch, crop or reframe the scene to fill "
                   "the white strip. If the first input already contains this strip, preserve it exactly. "
                   "Do not add captions, signatures or decorative text. Do not omit the bottom white strip.")
    return prompt.strip() + "\n\n[REQUIRED OUTPUT LAYOUT]\n" + layout + "\n"


def prepare_request(task, variant, prompt, images, mask_path=None):
    Image, _, _ = pillow()
    with task_lock(task) as state:
        require(state["status"] in ("draft", "approved"), "Task is closed.")
        variant_for(state, variant)
        width, height = state["plan"]["final_size"]
        bottom = state["plan"]["bottom_padding_px"]
        image_paths = [str(Path(p).resolve()) for p in images]
        for path in image_paths:
            require(Path(path).is_file() and Path(path).stat().st_size < 50 * 1024 * 1024,
                    "Input image is missing or exceeds 50 MB.")
        source_mask = None
        if mask_path:
            require(image_paths, "API mask needs an edit target.")
            with Image.open(mask_path) as mask, Image.open(image_paths[0]) as target:
                require(mask.format == "PNG" and "A" in mask.getbands() and mask.size == target.size,
                        "API mask must be alpha PNG matching the unpadded first input.")
                require(mask.getchannel("A").getextrema()[0] == 0, "API mask has no transparent editing area.")
                source_mask = mask.convert("RGBA")
        request_id = "p-" + uuid.uuid4().hex[:12]
        scratch = no_links(Path(state["work_dir"]) / "scratch")
        prepared_mask = str(Path(mask_path).resolve()) if mask_path else None
        if bottom and image_paths:
            target = read_image(image_paths[0])
            require(target.size == (width, height),
                    "Before-generation padding needs a first target matching final_size. "
                    "Choose supported dimensions before generating; no automatic resizing.")
            canvas = Image.new("RGBA", (width, height + bottom), (255, 255, 255, 255))
            canvas.paste(target, (0, 0))
            target_path = scratch / (request_id + "-target.png")
            save_png(canvas, target_path)
            track_file(state, target_path)
            image_paths[0] = str(target_path)
            if source_mask is not None:
                padded_mask = Image.new("RGBA", canvas.size, (255, 255, 255, 255))
                padded_mask.paste(source_mask, (0, 0))
                out_mask = scratch / (request_id + "-mask.png")
                save_png(padded_mask, out_mask)
                track_file(state, out_mask)
                prepared_mask = str(out_mask)
        prompt_path = scratch / (request_id + "-prompt.txt")
        with prompt_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(build_prompt(state, variant, prompt))
        track_file(state, prompt_path)
        request = {"id": request_id, "variant": variant, "plan_hash": state["plan_hash"],
                   "canvas_size": [width, height + bottom], "content_size": [width, height],
                   "bottom_padding_px": bottom, "prompt_file": str(prompt_path),
                   "images": image_paths, "mask": prepared_mask}
        request["fingerprints"] = {str(Path(p).resolve()): digest(p)
                                   for p in [str(prompt_path)] + image_paths + ([prepared_mask] if prepared_mask else [])}
        state.setdefault("preparations", {})[request_id] = request
        return request


def prepare(args):
    prompt = Path(args.prompt_file).read_text(encoding="utf-8-sig") if args.prompt_file else ""
    return prepare_request(args.task, args.variant, prompt, args.image, args.mask)


def check_result(args):
    _, state = check_task(args.task)
    return inspect_canvas(read_image(args.image), *state["plan"]["final_size"], state["plan"]["bottom_padding_px"])


def reserve(task, variant, method, prepared_id=None):
    with task_lock(task) as state:
        require(state["status"] == "approved", "Task must be approved and still open before generating.")
        variant_for(state, variant)
        if state["plan"]["bottom_padding_px"] or prepared_id:
            preparation = state.get("preparations", {}).get(prepared_id)
            require(preparation and preparation["variant"] == variant and preparation["plan_hash"] == state["plan_hash"],
                    "Run prepare first and pass --prepared ID; the white-band request is required before generation.")
            for path, fingerprint in preparation["fingerprints"].items():
                require(Path(path).is_file() and digest(path) == fingerprint,
                        "Prepared inputs or prompt changed; prepare a new request before generating.")
        require(len(state["attempts"]) < state["plan"]["max_generations"], "Generation budget exhausted.")
        related = [a for a in state["attempts"] if a["variant"] == variant]
        pending = sum(a["status"] in ("reserved", "review") for a in related)
        delivered = sum(item["variant"] == variant for item in state["deliveries"])
        require(delivered + pending < variant_for(state, variant)["count"],
                "All remaining image slots for this variant are pending review; resolve them before regenerating.")
        if len(related) >= 2:
            last = related[-2:]
            require(not (all(a["status"] == "failed" for a in last)
                         and last[0].get("reason") == last[1].get("reason")),
                    "Two consecutive failures with the same reason. Stop regenerating; choose another method.")
        require(delivered < variant_for(state, variant)["count"], "This variant already has its confirmed delivery count.")
        attempt = {"id": "a-" + uuid.uuid4().hex[:12], "variant": variant, "method": method,
                   "status": "reserved", "created": now(), "prepared": prepared_id}
        state["attempts"].append(attempt)
        return dict(attempt)


def record(task, attempt_id, image_path=None, reason=None):
    with task_lock(task) as state:
        attempt = attempt_for(state, attempt_id)
        require(attempt["status"] == "reserved", "Attempt has already been recorded.")
        if reason:
            attempt.update(status="failed", reason=slug(reason), finished=now())
            return dict(attempt)
        require(image_path is not None, "A generated image or failure reason is required.")
        image = read_image(image_path)
        return register_image(state, attempt, image)


def register_image(state, attempt, image):
    out = Path(state["work_dir"]) / "scratch" / (attempt["id"] + ".png")
    save_png(image, out)
    track_file(state, out)
    validation = inspect_canvas(image, *state["plan"]["final_size"], state["plan"]["bottom_padding_px"])
    attempt.update(status="review" if validation["valid"] else "failed", image=str(out),
                   finished=now(), validation=validation)
    if not validation["valid"]:
        attempt["reason"] = validation["issues"][0]
    return {**attempt, "validation_failed": not validation["valid"]}


def init_task(args):
    task_id = slug(args.id)
    plan = load_json(args.plan)
    validate_plan(plan)
    work = no_links(Path(args.work_root) / task_id)
    output = no_links(Path(args.output_root) / task_id)
    require(not inside(work, output) and not inside(output, work), "Work and output directories must be separate.")
    require(not work.exists() and not output.exists(), "Task or output directory already exists; use a unique task ID.")
    inputs = []
    for raw in plan["inputs"]:
        require(isinstance(raw, str), "Input paths must be strings.")
        path = Path(raw).resolve()
        require(path.is_file() and not inside(path, work) and not inside(path, output),
                "Inputs must exist outside this task's work and output directories.")
        inputs.append({"path": str(path), "sha256": digest(path)})
    plan["inputs"] = [item["path"] for item in inputs]
    (work / "scratch").mkdir(parents=True, exist_ok=False)
    marker = uuid.uuid4().hex
    (work / ".free-photo-edit-task").write_text(marker, encoding="utf-8")
    state = {"schema": 1, "marker": marker, "created": now(), "status": "draft",
             "work_dir": str(work), "output_dir": str(output), "plan": plan,
             "plan_hash": json_hash(plan), "inputs": inputs, "attempts": [], "deliveries": [], "temporary": {}}
    save_json(work / "task.json", state)
    return {"task": str(work / "task.json"), "status": "draft", "plan": plan}


def approve(args):
    require(args.confirmed, "Only approve after the user has confirmed the plan.")
    with task_lock(args.task) as state:
        require(state["status"] == "draft", "Only draft tasks can be approved.")
        state.update(status="approved", approved=now())
    return {"status": "approved"}


def status(args):
    _, state = check_task(args.task)
    return {"status": state["status"], "plan": state["plan"], "attempts_used": len(state["attempts"]),
            "attempts_remaining": state["plan"]["max_generations"] - len(state["attempts"]),
            "attempts": state["attempts"], "deliveries": state["deliveries"], "cost": "unknown"}


def reject(args):
    with task_lock(args.task) as state:
        attempt = attempt_for(state, args.attempt)
        require(attempt["status"] == "review", "Only unaccepted generated images can be rejected.")
        attempt.update(status="failed", reason=slug(args.reason))
    return {"status": "failed", "attempt": args.attempt, "reason": args.reason}


def deliver(args):
    require(args.reviewed, "Inspect the actual image first, then pass --reviewed.")
    Image, ImageChops, _ = pillow()
    with task_lock(args.task) as state:
        require(state["status"] == "approved", "Task is not open for delivery.")
        variant = variant_for(state, args.variant)
        sequence = sum(item["variant"] == args.variant for item in state["deliveries"]) + 1
        require(sequence <= variant["count"], "Delivery count would exceed the approved variant count.")
        attempt = None
        if args.attempt:
            attempt = attempt_for(state, args.attempt)
            require(attempt["variant"] == args.variant and attempt["status"] in ("review", "accepted"),
                    "Source attempt is not an eligible image for this variant.")
        else:
            require(args.source_note and args.source_note.strip(), "Local-only delivery needs --source-note describing its inputs and operations.")
        width, height = state["plan"]["final_size"]
        image, ratio = cropped(read_image(args.candidate), width, height, state["plan"]["bottom_padding_px"])
        pixel_verified = False
        if state["plan"]["preservation"] == "pixel":
            require(args.original and args.edit_mask, "Pixel preservation requires --original and --edit-mask.")
        if args.original or args.edit_mask:
            require(args.original and args.edit_mask, "Supply both --original and --edit-mask.")
            original_path = Path(args.original).resolve()
            original_info = next((v for v in state["inputs"] if v["path"] == str(original_path)), None)
            require(original_info is not None and digest(original_path) == original_info["sha256"],
                    "Preservation original must be an unchanged registered input.")
            original = read_image(original_path)
            with Image.open(args.edit_mask) as mask_file:
                mask = mask_file.convert("L")
            require(original.size == image.size == mask.size, "Original, content and edit mask sizes must match.")
            require(mask.getextrema()[0] == 0, "Edit mask must include a black protected area for preservation verification.")
            image = Image.composite(image, original, mask)
            protected = mask.point(lambda value: 255 if value == 0 else 0)
            difference = ImageChops.multiply(ImageChops.difference(image, original), Image.merge("RGBA", (protected,) * 4))
            require(all(high == 0 for low, high in difference.getextrema()), "Protected pixel verification failed.")
            pixel_verified = True
        output_dir = no_links(state["output_dir"])
        out = output_dir / (args.variant + "-" + str(sequence).zfill(2) + ".png")
        save_png(image, out)
        item = {"variant": args.variant, "path": str(out), "sha256": digest(out),
                "source_attempt": args.attempt, "source_note": args.source_note,
                "pixel_verified": pixel_verified, "bottom_white_ratio": ratio, "reviewed": now()}
        state["deliveries"].append(item)
        if attempt is not None:
            attempt["status"] = "accepted"
        expected = sum(v["count"] for v in state["plan"]["variants"])
        if len(state["deliveries"]) == expected and not any(a["status"] == "reserved" for a in state["attempts"]):
            state.update(status="complete", completed=now())
        return {"delivery": item, "task_status": state["status"]}


def crop(args):
    require(args.reviewed, "Inspect the reserved band first, then pass --reviewed.")
    require(args.bottom > 0, "Crop needs a positive bottom-band height.")
    image, ratio = cropped(read_image(args.image), args.expected_width, args.expected_height, args.bottom)
    save_png(image, args.out)
    return {"path": str(Path(args.out).resolve()), "size": image.size, "bottom_white_ratio": ratio}


def cleanup(args):
    with task_lock(args.task) as state:
        require(state["status"] == "complete", "Keep intermediate files until all confirmed deliveries are complete.")
        for item in state["deliveries"]:
            path = no_links(item["path"])
            require(path.is_file() and digest(path) == item["sha256"], "A delivery is missing or modified; do not clean intermediates yet.")
        deletable, skipped = [], []
        for raw, fingerprint in state["temporary"].items():
            try:
                path = owned_temp(state, raw)
                require(digest(path) == fingerprint, "Temporary file changed after registration.")
                deletable.append(path)
            except (WorkflowError, OSError):
                skipped.append(raw)
        # Recheck every path immediately before its own deletion.
        deleted = []
        if args.apply:
            for path in deletable:
                owned_temp(state, path)
                require(digest(path) == state["temporary"][str(path)], "Temporary file changed during cleanup.")
                path.unlink()
                state["temporary"].pop(str(path))
                deleted.append(str(path))
        scratch = no_links(Path(state["work_dir"]) / "scratch")
        # Unknown directories are reported whole, never recursively traversed.
        unknown = [str(p) for p in scratch.iterdir() if str(p.absolute()) not in state["temporary"]]
        return {"apply": args.apply, "eligible": [str(p) for p in deletable], "deleted": deleted,
                "skipped": skipped, "unregistered_kept": unknown}


def api(args):
    require(os.environ.get("OPENAI_API_KEY"), "OPENAI_API_KEY is missing; configure it locally, never paste it into chat.")
    require(not args.model.lower().endswith(("-luna", "-sol", "-astra", "-terra")),
            "Select an image-output model, not the controller language model.")
    try:
        from openai import OpenAI
    except ImportError:
        raise WorkflowError("openai missing. Use this interpreter's python -m pip install openai.")
    pillow()  # Fail before reserving a generation if local image validation cannot run.
    prompt = Path(args.prompt_file).read_text(encoding="utf-8-sig").strip()
    require(prompt, "Prompt file is empty.")
    prepared = prepare_request(args.task, args.variant, prompt, args.image, args.mask)
    prompt = Path(prepared["prompt_file"]).read_text(encoding="utf-8")
    canvas_size = "x".join(str(v) for v in prepared["canvas_size"])
    if args.size != "auto":
        require(args.size == canvas_size, "API size must match the confirmed content-plus-padding canvas before generating.")
    requested_size = canvas_size if prepared["bottom_padding_px"] else args.size
    attempt = reserve(args.task, args.variant, "api:" + args.model, prepared["id"])
    try:
        options = {"model": args.model, "prompt": prompt, "n": 1, "size": requested_size}
        if args.quality:
            options["quality"] = args.quality
        with OpenAI(max_retries=0, timeout=args.timeout) as client, ExitStack() as stack:
            if prepared["images"]:
                options["image"] = [stack.enter_context(Path(p).open("rb")) for p in prepared["images"]]
                if prepared["mask"]:
                    options["mask"] = stack.enter_context(Path(prepared["mask"]).open("rb"))
                response = client.images.edit(**options)
            else:
                response = client.images.generate(**options)
        require(response.data and len(response.data) == 1 and response.data[0].b64_json,
                "API returned no single base64 image; verify the provider result before retrying.")
        blob = base64.b64decode(response.data[0].b64_json, validate=True)
        from io import BytesIO
        Image, _, _ = pillow()
        with Image.open(BytesIO(blob)) as image:
            image.load()
            decoded = image.convert("RGBA")
        with task_lock(args.task) as state:
            current = attempt_for(state, attempt["id"])
            require(current["status"] == "reserved", "Attempt was updated by another command.")
            result = register_image(state, current, decoded)
        return {"attempt": attempt["id"], **result, "size": list(decoded.size)}
    except Exception as error:
        # Do not print raw exception bodies, request headers or provider credentials.
        try:
            record(args.task, attempt["id"], reason="api-error")
        except (WorkflowError, OSError):
            pass
        code = getattr(error, "status_code", None)
        message = "Generation failed; counted once, no automatic retry. Type=" + type(error).__name__
        if isinstance(code, int):
            message += "; HTTP=" + str(code)
        raise WorkflowError(message)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("init")
    for name in ("id", "plan", "work-root", "output-root"):
        p.add_argument("--" + name, required=True)
    p.set_defaults(func=init_task)
    for name, function in (("approve", approve), ("status", status), ("reserve", None),
                           ("record", None), ("reject", reject), ("track", None),
                           ("deliver", deliver), ("cleanup", cleanup), ("api", api),
                           ("prepare", prepare), ("check", check_result)):
        p = commands.add_parser(name)
        p.add_argument("--task", required=True)
        p.set_defaults(func=function)
        if name == "approve":
            p.add_argument("--confirmed", action="store_true")
        if name in ("reserve", "deliver", "api", "prepare"):
            p.add_argument("--variant", required=True)
        if name == "reserve":
            p.add_argument("--method", required=True)
            p.add_argument("--prepared")
        if name in ("record", "reject"):
            p.add_argument("--attempt", required=True)
            p.add_argument("--reason", required=name == "reject")
        if name == "record":
            group = p.add_mutually_exclusive_group(required=True)
            group.add_argument("--image")
            group.add_argument("--failed", action="store_true")
        if name == "track":
            p.add_argument("--file", required=True)
        if name == "deliver":
            p.add_argument("--candidate", required=True)
            for field in ("attempt", "original", "edit-mask", "source-note"):
                p.add_argument("--" + field)
            p.add_argument("--reviewed", action="store_true")
        if name == "cleanup":
            p.add_argument("--apply", action="store_true")
        if name in ("api", "prepare"):
            p.add_argument("--prompt-file", required=name == "api")
            p.add_argument("--image", action="append", default=[])
            p.add_argument("--mask")
        if name == "check":
            p.add_argument("--image", required=True)
        if name == "api":
            p.add_argument("--model", required=True)
            p.add_argument("--size", default="auto")
            p.add_argument("--quality", choices=("auto", "low", "medium", "high"))
            p.add_argument("--timeout", type=float, default=180)
    p = commands.add_parser("crop")
    for name in ("image", "out"):
        p.add_argument("--" + name, required=True)
    for name in ("bottom", "expected-width", "expected-height"):
        p.add_argument("--" + name, type=int, required=True)
    p.add_argument("--reviewed", action="store_true")
    p.set_defaults(func=crop)
    args = parser.parse_args(argv)
    try:
        if args.command == "reserve":
            result = reserve(args.task, args.variant, args.method, args.prepared)
        elif args.command == "record":
            require(not args.failed or args.reason, "Failed attempts need a short --reason tag.")
            require(not args.image or not args.reason, "Do not use a failure reason when recording an image.")
            result = record(args.task, args.attempt, args.image, args.reason if args.failed else None)
        elif args.command == "track":
            with task_lock(args.task) as state:
                track_file(state, args.file)
            result = {"tracked": str(Path(args.file).resolve())}
        else:
            result = args.func(args)
        emit(result)
        return 2 if result.get("validation_failed") or result.get("valid") is False else 0
    except (WorkflowError, OSError, ValueError, KeyError) as error:
        message = str(error)
        for key in (os.environ.get("OPENAI_API_KEY"),):
            if key:
                message = message.replace(key, "<redacted>")
        emit({"error": type(error).__name__, "message": message})
        return 2


if __name__ == "__main__":
    sys.exit(main())
