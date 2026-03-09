"""
Claude API Client – giao tiếp với Anthropic Claude API.
Hỗ trợ streaming để hiển thị response real-time trên frontend.
"""
import json
import frappe
import anthropic

# ── System prompt template ────────────────────────────────────────────────────
_SYSTEM_TEMPLATE = """\
{knowledge_base}

---

# CONTEXT DỰ ÁN HIỆN TẠI
Khách hàng: {customer}
Custom app sẽ tạo: {custom_app}
Base apps khách hàng mua: {purchased_apps}

---

# VAI TRÒ CỦA BẠN
Bạn là BA AI (Business Analyst AI) của hệ thống MBWNext ReqPilot.
Bạn đồng thời đóng 3 vai trò:

1. **ANALYST**: Đọc tài liệu yêu cầu, tự động extract từng yêu cầu và phân loại:
   - 🔴 MỚI: cần phát triển hoàn toàn mới
   - 🟡 PHẦN: đã có cơ sở trong base app, cần mở rộng
   - 🟢 CÓ SẴN: đã có sẵn, chỉ cần cấu hình
   Với mỗi yêu cầu, chỉ rõ: app nào xử lý, doctype/field nào liên quan.

2. **INTERVIEWER**: Chủ động đặt câu hỏi làm rõ các điểm mơ hồ trong yêu cầu.
   Hỏi từng điểm một, không hỏi dồn dập. Ưu tiên các điểm ảnh hưởng đến
   thiết kế kỹ thuật (doctype, workflow, tính toán).

3. **SRS WRITER**: Khi BA xác nhận đã đủ thông tin, tổng hợp thành SRS chuẩn
   với đầy đủ: mô tả nghiệp vụ, yêu cầu chức năng, ghi chú kỹ thuật (app/doctype/field).

# QUY TẮC QUAN TRỌNG
- Luôn trả lời bằng tiếng Việt
- Khi liệt kê yêu cầu, dùng JSON block để dễ parse:
  ```json
  {{"requirements": [...]}}
  ```
- Khi hỏi làm rõ, đánh số câu hỏi rõ ràng
- Mapping vào đúng app/doctype thực tế trong knowledge base, không bịa đặt
"""

_ANALYZE_PROMPT = """\
Dưới đây là tài liệu yêu cầu từ khách hàng:

---
{requirement_text}
---

Hãy:
1. Extract tất cả yêu cầu tính năng từ tài liệu trên
2. Với mỗi yêu cầu, phân tích gap so với các base apps khách hàng đã mua
3. Trả về danh sách yêu cầu theo format JSON:

```json
{{
  "requirements": [
    {{
      "req_id": "F-001",
      "requirement_text": "Mô tả yêu cầu",
      "gap_status": "🔴 MỚI | 🟡 PHẦN | 🟢 CÓ SẴN",
      "mapped_app": "tên app",
      "mapped_doctype": "tên doctype",
      "mapped_field": "field/feature cụ thể",
      "effort_days": 3,
      "priority": "Cao | Trung bình | Thấp",
      "dev_notes": "ghi chú kỹ thuật"
    }}
  ],
  "clarification_questions": [
    "Câu hỏi 1 cần làm rõ",
    "Câu hỏi 2 cần làm rõ"
  ],
  "summary": "Tóm tắt ngắn gọn"
}}
```

Sau JSON, hãy trình bày tóm tắt dễ đọc và đặt các câu hỏi làm rõ quan trọng nhất.
"""


def get_client() -> anthropic.Anthropic:
	settings = frappe.get_single("Reqpilot Settings")
	api_key = settings.get_password("claude_api_key")
	if not api_key:
		frappe.throw("Chưa cấu hình Claude API Key trong Reqpilot Settings")
	return anthropic.Anthropic(api_key=api_key)


def get_settings() -> dict:
	settings = frappe.get_single("Reqpilot Settings")
	return {
		"model": settings.claude_model or "claude-sonnet-4-6",
		"max_tokens": settings.max_tokens or 8192,
	}


def build_system_prompt(project_doc) -> str:
	"""Xây dựng system prompt với knowledge base + context dự án."""
	from mbwnext_reqpilot.mbwnext_reqpilot.services.app_indexer import build_knowledge_base

	purchased_apps = [row.app_name for row in project_doc.base_apps if row.included]
	knowledge_base = build_knowledge_base(purchased_apps)

	return _SYSTEM_TEMPLATE.format(
		knowledge_base=knowledge_base,
		customer=project_doc.customer or "Chưa xác định",
		custom_app=project_doc.custom_app_name or "mbwnext_custom",
		purchased_apps=", ".join(purchased_apps) or "Chưa chọn"
	)


def analyze_requirements(project_name: str) -> dict:
	"""
	Phân tích tài liệu yêu cầu lần đầu.
	Trả về dict với requirements list và câu hỏi làm rõ.
	"""
	project = frappe.get_doc("SRS Project", project_name)
	requirement_text = _get_requirement_text(project)

	if not requirement_text:
		frappe.throw("Chưa có nội dung yêu cầu. Hãy upload file hoặc nhập text.")

	client = get_client()
	cfg = get_settings()
	system_prompt = build_system_prompt(project)

	response = client.messages.create(
		model=cfg["model"],
		max_tokens=cfg["max_tokens"],
		system=system_prompt,
		messages=[{
			"role": "user",
			"content": _ANALYZE_PROMPT.format(requirement_text=requirement_text)
		}]
	)

	assistant_text = response.content[0].text

	# Parse JSON từ response
	parsed = _extract_json(assistant_text)

	# Lưu message vào chat history
	_save_message(project, "user", "message",
		_ANALYZE_PROMPT.format(requirement_text=requirement_text[:500] + "..."))
	_save_message(project, "assistant", "requirement", assistant_text)

	# Cập nhật requirements table
	if parsed and parsed.get("requirements"):
		project.requirements = []
		for i, req in enumerate(parsed["requirements"]):
			project.append("requirements", {
				"req_id": req.get("req_id", f"F-{i+1:03d}"),
				"requirement_text": req.get("requirement_text", ""),
				"gap_status": req.get("gap_status", ""),
				"mapped_app": req.get("mapped_app", ""),
				"mapped_doctype": req.get("mapped_doctype", ""),
				"mapped_field": req.get("mapped_field", ""),
				"effort_days": req.get("effort_days", 0),
				"priority": req.get("priority", ""),
				"dev_notes": req.get("dev_notes", ""),
				"clarified": 0
			})

	project.status = "Analyzing"
	project.save(ignore_permissions=True)
	frappe.db.commit()

	return {
		"message": assistant_text,
		"requirements": parsed.get("requirements", []) if parsed else [],
		"questions": parsed.get("clarification_questions", []) if parsed else []
	}


def chat(project_name: str, user_message: str) -> str:
	"""
	Gửi tin nhắn từ BA và nhận phản hồi từ Claude (non-streaming).
	Lưu toàn bộ hội thoại vào SRS Project.
	"""
	project = frappe.get_doc("SRS Project", project_name)
	client = get_client()
	cfg = get_settings()
	system_prompt = build_system_prompt(project)

	# Build messages history từ chat_messages
	messages = _build_messages_history(project)
	messages.append({"role": "user", "content": user_message})

	response = client.messages.create(
		model=cfg["model"],
		max_tokens=cfg["max_tokens"],
		system=system_prompt,
		messages=messages
	)

	assistant_text = response.content[0].text

	# Lưu cả 2 message
	_save_message(project, "user", "message", user_message)
	_save_message(project, "assistant", "message", assistant_text)

	project.status = "Clarifying"
	project.save(ignore_permissions=True)
	frappe.db.commit()

	return assistant_text


def stream_chat(project_name: str, user_message: str):
	"""
	Streaming version – yield từng chunk text.
	Dùng với Server-Sent Events (SSE) trên frontend.
	"""
	project = frappe.get_doc("SRS Project", project_name)
	client = get_client()
	cfg = get_settings()
	system_prompt = build_system_prompt(project)

	messages = _build_messages_history(project)
	messages.append({"role": "user", "content": user_message})

	full_text = []
	with client.messages.stream(
		model=cfg["model"],
		max_tokens=cfg["max_tokens"],
		system=system_prompt,
		messages=messages
	) as stream:
		for text_chunk in stream.text_stream:
			full_text.append(text_chunk)
			yield text_chunk

	assistant_text = "".join(full_text)
	_save_message(project, "user", "message", user_message)
	_save_message(project, "assistant", "message", assistant_text)
	project.status = "Clarifying"
	project.save(ignore_permissions=True)
	frappe.db.commit()


def generate_srs_prompt(project_name: str) -> str:
	"""
	Yêu cầu Claude tổng hợp SRS từ toàn bộ hội thoại.
	Trả về text SRS đầy đủ để srs_generator.py dùng.
	"""
	project = frappe.get_doc("SRS Project", project_name)
	client = get_client()
	cfg = get_settings()
	system_prompt = build_system_prompt(project)

	messages = _build_messages_history(project)
	messages.append({
		"role": "user",
		"content": (
			"Dựa trên toàn bộ phân tích và làm rõ ở trên, hãy viết tài liệu SRS đầy đủ theo cấu trúc:\n\n"
			"Với MỖI tính năng:\n"
			"1. Mô tả nghiệp vụ\n"
			"2. Phạm vi hệ thống (app/doctype/field cụ thể trong knowledge base)\n"
			"3. Yêu cầu chức năng (bảng: Mã YC | Mô tả | Ghi chú kỹ thuật)\n"
			"4. Trạng thái: 🔴/🟡/🟢\n\n"
			"Và phần phụ lục:\n"
			"- Bảng tổng hợp tất cả requirements\n"
			"- Custom field cần bổ sung mới\n"
			"- Câu hỏi còn chưa làm rõ (nếu có)\n\n"
			"Trả lời bằng Markdown có cấu trúc rõ ràng."
		)
	})

	response = client.messages.create(
		model=cfg["model"],
		max_tokens=cfg["max_tokens"],
		system=system_prompt,
		messages=messages
	)

	srs_text = response.content[0].text
	_save_message(project, "assistant", "summary", srs_text)
	project.save(ignore_permissions=True)
	frappe.db.commit()

	return srs_text


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_requirement_text(project) -> str:
	"""Lấy text yêu cầu: ưu tiên file upload, fallback về text field."""
	text = project.requirement_text or ""

	if project.requirement_files:
		file_path = frappe.get_doc("File", {"file_url": project.requirement_files}).get_full_path()
		ext = os.path.splitext(file_path)[1].lower()
		if ext == ".pdf":
			text = _extract_pdf(file_path) + "\n\n" + text
		elif ext in (".docx", ".doc"):
			text = _extract_docx(file_path) + "\n\n" + text

	return text.strip()


def _extract_pdf(path: str) -> str:
	try:
		import fitz  # pymupdf
		doc = fitz.open(path)
		return "\n".join(page.get_text() for page in doc)
	except Exception as e:
		return f"[Không đọc được PDF: {e}]"


def _extract_docx(path: str) -> str:
	try:
		from docx import Document
		doc = Document(path)
		return "\n".join(p.text for p in doc.paragraphs)
	except Exception as e:
		return f"[Không đọc được DOCX: {e}]"


def _build_messages_history(project) -> list:
	"""Chuyển chat_messages table thành list messages cho Claude API."""
	messages = []
	for msg in project.chat_messages:
		if msg.role in ("user", "assistant"):
			messages.append({"role": msg.role, "content": msg.content})
	return messages


def _save_message(project, role: str, msg_type: str, content: str):
	from frappe.utils import now_datetime
	project.append("chat_messages", {
		"role": role,
		"message_type": msg_type,
		"timestamp": now_datetime(),
		"content": content
	})


def _extract_json(text: str) -> dict | None:
	"""Tìm và parse JSON block đầu tiên trong response."""
	import re
	pattern = r"```json\s*([\s\S]*?)\s*```"
	match = re.search(pattern, text)
	if match:
		try:
			return json.loads(match.group(1))
		except json.JSONDecodeError:
			pass
	return None


import os
