frappe.pages["reqpilot"].on_page_load = function (wrapper) {
	frappe.require([
		"/assets/mbwnext_reqpilot/js/reqpilot_app.js",
		"/assets/mbwnext_reqpilot/css/reqpilot.css",
	], function () {
		const page = frappe.ui.make_app_page({
			parent: wrapper,
			title: "ReqPilot – BA AI",
			single_column: true,
		});
		window.reqpilot_page = page;
		// Mount Vue app vào container
		const container = document.createElement("div");
		container.id = "reqpilot-root";
		page.main.append(container);

		// ReqPilotApp may already be set (Vue was bundled/cached)
		// or it will be set after CDN Vue loads (async), in which case
		// mountApp() in reqpilot_app.js will auto-mount because the container now exists
		if (window.ReqPilotApp) {
			window.ReqPilotApp.mount("#reqpilot-root");
		}
		// else: reqpilot_app.js CDN onload callback will mount once Vue is ready
	});
};
