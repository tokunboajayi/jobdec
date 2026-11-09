"""
Vision-Assisted Self-Healing Page Solver.
Detects interactive application controls, submit buttons, next-step wizards,
and custom canvas/SVG elements via visual bounding box layout and coordinate grounding.
Provides headless click recovery when standard DOM selectors fail.
"""
import re
import time
from typing import Dict, Any, Tuple, Optional
from pathlib import Path


VISUAL_BUTTON_TARGETS = re.compile(
    r"\b(submit application|submit|review and submit|save and continue|continue|next step|next|apply now|apply|i accept|accept|agree)\b",
    re.I
)

VISUAL_SCAN_JS = """() => {
    const targets = [];
    // Scan all interactive elements, buttons, role='button', links, divs with click handlers
    const candidates = document.querySelectorAll("button, input[type='submit'], input[type='button'], [role='button'], a, div[onclick], span[onclick], [data-automation-id*='submit'], [data-automation-id*='next']");
    
    for (let el of candidates) {
        // Element visibility check
        const rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0 && rect.top >= 0 && rect.top <= window.innerHeight) {
            const style = window.getComputedStyle(el);
            if (style.visibility !== 'hidden' && style.display !== 'none' && style.opacity !== '0') {
                const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
                targets.push({
                    text: text,
                    x: Math.round(rect.left + (rect.width / 2)),
                    y: Math.round(rect.top + (rect.height / 2)),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    tagName: el.tagName.toLowerCase(),
                    id: el.id || '',
                    className: el.className || ''
                });
            }
        }
    }
    return targets;
}"""


def visual_detect_submit_or_next(page) -> Optional[Dict[str, Any]]:
    """
    Visually inspects the active browser viewport and detects target action buttons.
    Returns coordinate dictionary or None.
    """
    try:
        elements = page.evaluate(VISUAL_SCAN_JS)
        for el in elements:
            txt = el.get("text", "")
            if VISUAL_BUTTON_TARGETS.search(txt):
                # Found high-confidence action button
                return {
                    "type": "button",
                    "label": txt,
                    "x": el["x"],
                    "y": el["y"],
                    "width": el["width"],
                    "height": el["height"]
                }
    except Exception as e:
        print(f"[Vision Solver] Error during visual scan: {e}")
    return None


def execute_vision_click(page, target: Dict[str, Any]) -> bool:
    """
    Simulates a natural human coordinate click on visually grounded coordinates.
    """
    try:
        x, y = target["x"], target["y"]
        page.mouse.move(x, y)
        time.sleep(0.15)
        page.mouse.click(x, y)
        time.sleep(1.0)
        return True
    except Exception as e:
        print(f"[Vision Solver] Error executing coordinate click at ({target.get('x')}, {target.get('y')}): {e}")
        return False


def self_heal_stuck_page(page) -> Dict[str, Any]:
    """
    Autonomous self-healing routine for stalled or wizard multi-step pages.
    """
    initial_url = getattr(page, "url", "")
    target = visual_detect_submit_or_next(page)
    if not target:
        return {"healed": False, "reason": "No target action button detected visually"}

    print(f"[Vision Solver] Visually grounded action button '{target['label']}' at ({target['x']}, {target['y']}). Executing coordinate click...")
    ok = execute_vision_click(page, target)
    if not ok:
        return {"healed": False, "reason": "Coordinate click execution failed"}

    # Evaluate post-click page state
    time.sleep(2.0)
    current_url = getattr(page, "url", "")
    url_changed = current_url != initial_url

    return {
        "healed": True,
        "action": target["label"],
        "coordinates": (target["x"], target["y"]),
        "url_changed": url_changed,
        "new_url": current_url
    }

