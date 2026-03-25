import logging
from app.agents.planner_agent import plan_work_request
from app.services.llm_service import generate_response

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ASSISTANT_SYSTEM_PROMPT = """คุณเป็นผู้ช่วยส่วนตัวที่ช่วยเหลือผู้ใช้ในงานต่างๆ

กฎ:
1. ตอบกลับสั้น กระชับ
2. ถ้ายังไม่มีข้อมูล enough ให้ถามเพิ่ม
3. ห้ามแกล้งทำเป็นว่าทำงานเสร็จแล้ว
4. ให้ข้อมูล ข้อเสนอแนะ หรือ ร่างเอกสาร ได้
5. พูดไทย"""

REQUEST_TYPE_PROMPTS = {
    "create_slide": "ช่วยเสนอไอเดียสำหรับสร้างสไลด์ 5-7 หน้า",
    "write_doc": "ช่วยเขียนโครงร่างเอกสาร",
    "research": "ช่วยหาข้อมูลเบื้องต้นเกี่ยวกับ",
    "summarize": "ช่วยสรุปประเด็นสำคัญของ",
    "draft_email": "ช่วยร่างอีเมล",
    "brainstorm": "ช่วยคิดไอเดียเกี่ยวกับ",
    "schedule": "ช่วยเสนอวิธีการจัดตาราง"
}


def handle_work_request(text: str) -> str:
    logger.info(f"work_request: {text}")
    
    plan = plan_work_request(text)
    logger.info(f"Planner result: {plan}")
    
    if plan.get("needs_clarification"):
        return plan.get("clarification_question", "ขอรายละเอียดเพิ่มอีกนิดนะครับ")
    
    if plan.get("can_answer_directly"):
        request_type = plan.get("request_type", "general")
        prompt_suffix = REQUEST_TYPE_PROMPTS.get(request_type, "")
        full_prompt = f"{prompt_suffix}: {text}"
        
        response = generate_response(ASSISTANT_SYSTEM_PROMPT, full_prompt)
        logger.info(f"LLM response: {response[:100]}...")
        return response
    
    return "ขอรายละเอียดเพิ่มอีกนิดนะครับ เพื่อช่วยคุณได้ตรงจุดมากขึ้น"