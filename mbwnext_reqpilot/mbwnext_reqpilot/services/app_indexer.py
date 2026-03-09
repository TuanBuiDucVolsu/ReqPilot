"""
App Indexer – đọc source code của base apps và lưu vào Base App Catalog.
Chạy thủ công hoặc qua scheduled job hàng ngày.
"""
import os
import json
import frappe
from frappe.utils import now_datetime


def index_all_apps():
	"""Index tất cả base apps được cấu hình trong Reqpilot Settings."""
	settings = frappe.get_single("Reqpilot Settings")
	bench_path = settings.bench_path or _detect_bench_path()
	if not bench_path or not os.path.isdir(bench_path):
		frappe.throw(f"Bench path không hợp lệ: {bench_path}")

	base_apps = [a.strip() for a in (settings.base_apps or "").splitlines() if a.strip()]
	results = []
	for app_name in base_apps:
		try:
			result = index_app(app_name, bench_path)
			results.append(result)
		except Exception as e:
			frappe.log_error(f"Error indexing {app_name}: {e}", "App Indexer")

	settings.last_indexed = now_datetime()
	settings.save(ignore_permissions=True)
	return results


def index_app(app_name: str, bench_path: str) -> dict:
	"""Index 1 app – đọc hooks.py, doctypes, custom fields, reports."""
	app_path = os.path.join(bench_path, app_name)
	if not os.path.isdir(app_path):
		frappe.throw(f"App path không tồn tại: {app_path}")

	# Lấy metadata từ hooks.py
	meta = _read_hooks(app_path, app_name)

	# Thu thập features
	features = []
	features += _index_doctypes(app_path, app_name)
	features += _index_custom_fields(app_path)
	features += _index_reports(app_path, app_name)
	features += _index_pages(app_path, app_name)
	features += _index_hooks_events(app_path, app_name)

	# Lưu / cập nhật Base App Catalog
	if frappe.db.exists("Base App Catalog", app_name):
		doc = frappe.get_doc("Base App Catalog", app_name)
	else:
		doc = frappe.new_doc("Base App Catalog")
		doc.app_name = app_name

	doc.app_title = meta.get("app_title", app_name)
	doc.version = meta.get("app_version", "")
	doc.description = meta.get("app_description", "")
	doc.last_indexed = now_datetime()
	doc.features = []
	for f in features:
		doc.append("features", f)

	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"app": app_name, "features": len(features)}


def _detect_bench_path() -> str:
	"""Tự detect bench apps path từ frappe.__version__."""
	try:
		import frappe as _f
		app_path = os.path.dirname(os.path.dirname(_f.__file__))
		return app_path  # .../bench/apps
	except Exception:
		return ""


def _read_hooks(app_path: str, app_name: str) -> dict:
	hooks_file = os.path.join(app_path, app_name, "hooks.py")
	meta = {}
	if not os.path.exists(hooks_file):
		return meta
	ns = {}
	try:
		with open(hooks_file) as f:
			exec(f.read(), ns)  # noqa
		for key in ("app_title", "app_version", "app_description", "app_publisher"):
			meta[key] = ns.get(key, "")
	except Exception:
		pass
	return meta


def _index_doctypes(app_path: str, app_name: str) -> list:
	features = []
	module_dirs = [
		d for d in os.listdir(app_path)
		if os.path.isdir(os.path.join(app_path, d)) and not d.startswith(".")
	]
	for mod in module_dirs:
		doctype_dir = os.path.join(app_path, mod, "doctype")
		if not os.path.isdir(doctype_dir):
			continue
		for dt_name in os.listdir(doctype_dir):
			json_file = os.path.join(doctype_dir, dt_name, f"{dt_name}.json")
			if not os.path.isfile(json_file):
				continue
			try:
				with open(json_file) as f:
					dt_def = json.load(f)
				fields = [
					fld.get("fieldname")
					for fld in dt_def.get("fields", [])
					if fld.get("fieldtype") not in ("Section Break", "Column Break", "HTML", "Heading")
				]
				is_table = dt_def.get("istable", 0)
				feat_type = "Child Table" if is_table else "Doctype"
				features.append({
					"doctype_name": dt_def.get("name", dt_name),
					"feature_type": "Doctype",
					"feature_description": f"[{feat_type}] Fields: {', '.join(fields[:15])}",
					"raw_json": json.dumps(fields)
				})
			except Exception:
				pass
	return features


def _index_custom_fields(app_path: str) -> list:
	"""Đọc fixtures/custom_field.json nếu có."""
	features = []
	for root, dirs, files in os.walk(app_path):
		if "fixtures" in root and "custom_field.json" in files:
			try:
				with open(os.path.join(root, "custom_field.json")) as f:
					cfs = json.load(f)
				# Nhóm theo doctype
				grouped = {}
				for cf in cfs:
					dt = cf.get("dt", "Unknown")
					grouped.setdefault(dt, []).append(
						f"{cf.get('fieldname')} ({cf.get('fieldtype')})"
					)
				for dt, fields in grouped.items():
					features.append({
						"doctype_name": dt,
						"feature_type": "Custom Field",
						"feature_description": f"Custom fields: {', '.join(fields[:10])}",
						"raw_json": json.dumps(fields)
					})
			except Exception:
				pass
	return features


def _index_reports(app_path: str, app_name: str) -> list:
	features = []
	for root, dirs, files in os.walk(app_path):
		for fname in files:
			if fname.endswith(".json") and "report" in root:
				try:
					with open(os.path.join(root, fname)) as f:
						rpt = json.load(f)
					if rpt.get("report_name"):
						features.append({
							"doctype_name": rpt.get("report_name"),
							"feature_type": "Report",
							"feature_description": f"Report on {rpt.get('ref_doctype', '')} – type: {rpt.get('report_type', '')}",
							"raw_json": ""
						})
				except Exception:
					pass
	return features


def _index_pages(app_path: str, app_name: str) -> list:
	features = []
	for root, dirs, files in os.walk(app_path):
		if "page" in root.split(os.sep):
			for fname in files:
				if fname.endswith(".json"):
					try:
						with open(os.path.join(root, fname)) as f:
							pg = json.load(f)
						if pg.get("name") and pg.get("doctype") == "Page":
							features.append({
								"doctype_name": pg.get("name"),
								"feature_type": "Page",
								"feature_description": f"Page: {pg.get('title', pg.get('name'))}",
								"raw_json": ""
							})
					except Exception:
						pass
	return features


def _index_hooks_events(app_path: str, app_name: str) -> list:
	"""Đọc doc_events từ hooks.py."""
	features = []
	hooks_file = os.path.join(app_path, app_name, "hooks.py")
	if not os.path.exists(hooks_file):
		return features
	ns = {}
	try:
		with open(hooks_file) as f:
			exec(f.read(), ns)  # noqa
		doc_events = ns.get("doc_events", {})
		if doc_events:
			summary = []
			for dt, events in doc_events.items():
				summary.append(f"{dt}: {', '.join(events.keys())}")
			features.append({
				"doctype_name": "Doc Events (hooks.py)",
				"feature_type": "Hook",
				"feature_description": " | ".join(summary[:10]),
				"raw_json": json.dumps(doc_events, default=str)
			})
	except Exception:
		pass
	return features


def build_knowledge_base(app_names: list) -> str:
	"""
	Tổng hợp knowledge base dạng text để inject vào system prompt của Claude.
	Gọi mỗi khi tạo chat session mới.
	"""
	lines = ["# KNOWLEDGE BASE – CÁC APP MBWNEXT\n"]
	lines.append("Bạn là chuyên gia phân tích nghiệp vụ ERP (Frappe/ERPNext).")
	lines.append("Hệ thống MBWNext có các base app sau đây với tính năng như mô tả bên dưới.\n")

	for app_name in app_names:
		if not frappe.db.exists("Base App Catalog", app_name):
			continue
		catalog = frappe.get_doc("Base App Catalog", app_name)
		lines.append(f"\n## App: {catalog.app_title} ({app_name}) – v{catalog.version}")
		lines.append(f"Mô tả: {catalog.description}")

		# Nhóm theo feature_type
		by_type = {}
		for feat in catalog.features:
			by_type.setdefault(feat.feature_type, []).append(feat)

		for ftype, feats in by_type.items():
			lines.append(f"\n### {ftype}:")
			for feat in feats[:30]:  # giới hạn để không quá dài
				lines.append(f"  - {feat.doctype_name}: {feat.feature_description}")

	return "\n".join(lines)
