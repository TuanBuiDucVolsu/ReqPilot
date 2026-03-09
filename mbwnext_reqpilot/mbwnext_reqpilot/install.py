import frappe


def after_install():
	"""Thiết lập mặc định sau khi cài app."""
	import os

	# Tạo Reqpilot Settings với bench_path mặc định
	if not frappe.db.exists("Reqpilot Settings", "Reqpilot Settings"):
		return

	settings = frappe.get_single("Reqpilot Settings")

	# Tự detect bench apps path
	try:
		bench_apps = os.path.dirname(os.path.dirname(frappe.__file__))
		if os.path.isdir(bench_apps):
			settings.bench_path = bench_apps
	except Exception:
		pass

	# Danh sách base apps mặc định
	default_apps = [
		"mbwnext_advanced_selling",
		"mbwnext_advanced_buying",
		"mbwnext_advanced_stock",
		"mbwnext_advanced_accounting",
		"mbwnext_localization",
	]
	existing = [
		a for a in default_apps
		if os.path.isdir(os.path.join(settings.bench_path or "", a))
	]
	if existing:
		settings.base_apps = "\n".join(existing)

	settings.save(ignore_permissions=True)
	frappe.db.commit()
	frappe.msgprint("✅ ReqPilot đã cài đặt. Vào Reqpilot Settings để cấu hình Claude API Key.")
