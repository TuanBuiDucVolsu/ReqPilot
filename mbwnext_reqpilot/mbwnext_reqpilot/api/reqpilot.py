"""
Frappe API endpoints cho ReqPilot.
Tất cả endpoint dùng @frappe.whitelist() để Vue.js gọi được.
"""
import json
import frappe
from frappe.utils import now_datetime


# ── App Indexer ───────────────────────────────────────────────────────────────

@frappe.whitelist()
def index_apps():
	"""Index tất cả base apps trong Reqpilot Settings."""
	from mbwnext_reqpilot.mbwnext_reqpilot.services.app_indexer import index_all_apps
	try:
		results = index_all_apps()
		return {"status": "ok", "results": results}
	except Exception as e:
		frappe.log_error(str(e), "ReqPilot Index Apps")
		return {"status": "error", "message": str(e)}


@frappe.whitelist()
def get_catalog():
	"""Lấy danh sách Base App Catalog để hiển thị trên UI."""
	apps = frappe.get_all(
		"Base App Catalog",
		fields=["app_name", "app_title", "version", "description", "last_indexed"],
		order_by="app_name"
	)
	return apps


# ── Project ───────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_projects():
	"""Danh sách SRS Project."""
	return frappe.get_all(
		"SRS Project",
		fields=["name", "project_name", "customer", "status", "custom_app_name",
				"created_by_user", "creation_date", "modified"],
		order_by="modified desc",
		limit=50
	)


@frappe.whitelist()
def get_project(project_name: str):
	"""Chi tiết 1 SRS Project."""
	doc = frappe.get_doc("SRS Project", project_name)
	data = doc.as_dict()
	return data


@frappe.whitelist()
def create_project(project_name: str, customer: str = "", custom_app_name: str = "",
				   base_apps: str = "[]"):
	"""Tạo mới SRS Project."""
	apps_list = json.loads(base_apps) if isinstance(base_apps, str) else base_apps

	doc = frappe.new_doc("SRS Project")
	doc.project_name = project_name
	doc.customer = customer
	doc.custom_app_name = custom_app_name
	doc.created_by_user = frappe.session.user
	for app in apps_list:
		doc.append("base_apps", {"app_name": app, "included": 1})

	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name, "status": "created"}


@frappe.whitelist()
def delete_project(project_name: str):
	"""Xóa 1 SRS Project."""
	doc = frappe.get_doc("SRS Project", project_name)
	doc.delete(ignore_permissions=True)
	frappe.db.commit()
	return {"status": "ok"}


@frappe.whitelist()
def update_requirement_text(project_name: str, text: str):
	"""Cập nhật requirement_text."""
	doc = frappe.get_doc("SRS Project", project_name)
	doc.requirement_text = text
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"status": "ok"}


@frappe.whitelist()
def update_requirement_item(project_name: str, req_id: str, field: str, value: str):
	"""Cập nhật 1 trường trong SRS Requirement row."""
	doc = frappe.get_doc("SRS Project", project_name)
	for req in doc.requirements:
		if req.req_id == req_id:
			setattr(req, field, value)
			break
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"status": "ok"}


# ── File Upload ───────────────────────────────────────────────────────────────

@frappe.whitelist()
def extract_file_text(project_name: str, file_url: str):
	"""
	Đọc nội dung file (PDF/DOCX) đã upload và lưu vào requirement_text.
	"""
	import os
	import textwrap
	try:
		file_doc = frappe.get_doc("File", {"file_url": file_url})
		file_path = file_doc.get_full_path()
		ext = os.path.splitext(file_path)[1].lower()

		text = ""
		if ext == ".pdf":
			try:
				from PyPDF2 import PdfReader
			except ImportError as ie:
				frappe.throw(f"Thiếu thư viện PyPDF2 để đọc PDF: {ie}")

			with open(file_path, "rb") as f:
				reader = PdfReader(f)
				raw = "\n".join((page.extract_text() or "") for page in reader.pages)
				# Gộp các dòng liên tiếp thành đoạn, tránh xuống dòng giữa mỗi chữ
				text = _normalize_paragraphs(raw)
		elif ext in (".docx", ".doc"):
			from docx import Document
			d = Document(file_path)
			raw = "\n".join(p.text for p in d.paragraphs)
			text = _normalize_paragraphs(raw)
		else:
			frappe.throw(f"Định dạng file không hỗ trợ: {ext}")

		# Lưu vào project
		doc = frappe.get_doc("SRS Project", project_name)
		doc.requirement_files = file_url
		doc.requirement_text = text.strip()
		doc.save(ignore_permissions=True)
		frappe.db.commit()

		return {"status": "ok", "text": text[:500] + "..." if len(text) > 500 else text}
	except Exception as e:
		frappe.log_error(str(e), "ReqPilot Extract File")
		return {"status": "error", "message": str(e)}


def _normalize_paragraphs(raw: str) -> str:
	"""Gộp các dòng liên tiếp thành đoạn văn, giữ lại khoảng trắng hợp lý."""
	lines = [ln.strip() for ln in (raw or "").splitlines()]
	paragraphs = []
	buf = []

	for ln in lines:
		# Dòng trống: kết thúc một đoạn
		if not ln:
			if buf:
				paragraphs.append(" ".join(buf))
				buf = []
			continue
		buf.append(ln)

	if buf:
		paragraphs.append(" ".join(buf))

	# Giới hạn chiều rộng hiển thị để dễ đọc, nhưng vẫn là text thuần
	return "\n\n".join(paragraphs)


# ── AI Analysis ───────────────────────────────────────────────────────────────

@frappe.whitelist()
def analyze(project_name: str):
	"""
	Phân tích yêu cầu lần đầu bằng Claude.
	Trả về requirements list + câu hỏi làm rõ.
	"""
	from mbwnext_reqpilot.mbwnext_reqpilot.services.claude_client import analyze_requirements
	try:
		result = analyze_requirements(project_name)
		return {"status": "ok", **result}
	except Exception as e:
		msg = str(e)
		if "Request too large for model" in msg or "code: 413" in msg:
			user_msg = (
				"Tài liệu hoặc context hiện tại quá dài so với giới hạn của mô hình LLM. "
				"Hãy chia nhỏ tài liệu, bớt phần không cần thiết hoặc chạy lại cho từng module."
			)
		else:
			user_msg = msg

		# Tránh lỗi Error Log do title quá dài
		frappe.log_error(message=user_msg[:1000], title="ReqPilot Analyze")
		return {"status": "error", "message": user_msg}


@frappe.whitelist()
def chat(project_name: str, message: str):
	"""
	Gửi tin nhắn chat từ BA, nhận phản hồi từ Claude.
	Non-streaming – phù hợp với simple AJAX call.
	"""
	from mbwnext_reqpilot.mbwnext_reqpilot.services.claude_client import chat as claude_chat
	try:
		reply = claude_chat(project_name, message)
		return {"status": "ok", "message": reply}
	except Exception as e:
		frappe.log_error(str(e), "ReqPilot Chat")
		return {"status": "error", "message": str(e)}


@frappe.whitelist(allow_guest=False)
def stream_chat(project_name: str, message: str):
	"""
	Streaming chat endpoint – dùng Server-Sent Events.
	Frontend gọi qua EventSource hoặc fetch với ReadableStream.
	"""
	from mbwnext_reqpilot.mbwnext_reqpilot.services.claude_client import stream_chat as _stream

	frappe.local.response.update({
		"type": "text/event-stream",
		"charset": "utf-8"
	})

	full_response = []
	try:
		for chunk in _stream(project_name, message):
			full_response.append(chunk)
			# SSE format
			frappe.local.response["data"] = f"data: {json.dumps({'chunk': chunk})}\n\n"
	except Exception as e:
		frappe.log_error(str(e), "ReqPilot Stream Chat")

	# Final message signal
	return {"status": "done", "full": "".join(full_response)}


# ── SRS Generator ─────────────────────────────────────────────────────────────

@frappe.whitelist()
def generate_srs(project_name: str):
	"""
	Sinh file SRS DOCX từ kết quả phân tích và hội thoại.
	Trả về file_url để download.
	"""
	from mbwnext_reqpilot.mbwnext_reqpilot.services.srs_generator import generate
	try:
		file_url = generate(project_name)
		return {"status": "ok", "file_url": file_url}
	except Exception as e:
		msg = str(e)
		if "Rate limit reached for model" in msg or "code: 429" in msg:
			user_msg = (
				"Bạn đã chạm giới hạn số token/ngày của model LLM trên Groq. "
				"Hãy đợi thêm một lúc (khoảng 1–2 giờ) rồi thử lại, "
				"hoặc chuyển sang model khác / nâng gói trên Groq."
			)
		else:
			user_msg = msg

		frappe.log_error(message=user_msg[:1000], title="ReqPilot Generate SRS")
		return {"status": "error", "message": user_msg}


# ── Chat History ──────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_chat_history(project_name: str):
	"""Lấy lịch sử chat để render lại khi reload."""
	doc = frappe.get_doc("SRS Project", project_name)
	messages = []
	for msg in doc.chat_messages:
		if msg.role in ("user", "assistant"):
			messages.append({
				"role": msg.role,
				"type": msg.message_type,
				"content": msg.content,
				"timestamp": str(msg.timestamp)
			})
	return messages


@frappe.whitelist()
def clear_chat(project_name: str):
	"""Xóa toàn bộ lịch sử chat (reset để phân tích lại)."""
	doc = frappe.get_doc("SRS Project", project_name)
	doc.chat_messages = []
	doc.requirements = []
	doc.status = "Draft"
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"status": "ok"}
