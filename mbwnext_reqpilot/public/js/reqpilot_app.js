/* ============================================================
   ReqPilot Vue 3 App  (CDN build – no bundler needed)
   Mount vào #reqpilot-root từ reqpilot.js (Frappe Page)
   ============================================================ */

(function () {
  "use strict";

  // ── API helper ──────────────────────────────────────────────
  const api = {
    call(method, args = {}) {
      return new Promise((resolve, reject) => {
        frappe.call({
          method: `mbwnext_reqpilot.mbwnext_reqpilot.api.reqpilot.${method}`,
          args,
          callback: (r) => (r.exc ? reject(r.exc) : resolve(r.message)),
        });
      });
    },
  };

  // ── Markdown → HTML (simple) ────────────────────────────────
  function mdToHtml(text) {
    if (!text) return "";
    return text
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`(.+?)`/g, "<code>$1</code>")
      .replace(/^### (.+)$/gm, "<h6 style='margin:8px 0 4px;font-weight:700'>$1</h6>")
      .replace(/^## (.+)$/gm, "<h5 style='margin:10px 0 4px;font-weight:700'>$1</h5>")
      .replace(/^# (.+)$/gm, "<h4 style='margin:10px 0 4px;font-weight:700'>$1</h4>")
      .replace(/^[-*] (.+)$/gm, "<li style='margin-left:16px'>$1</li>")
      .replace(/🔴/g, '<span style="color:#C53030">🔴</span>')
      .replace(/🟡/g, '<span style="color:#C05621">🟡</span>')
      .replace(/🟢/g, '<span style="color:#276749">🟢</span>')
      .replace(/\n/g, "<br>");
  }

  // ── Gap status helper ────────────────────────────────────────
  function gapClass(status) {
    if (!status) return "";
    if (status.includes("MỚI")) return "new";
    if (status.includes("PHẦN")) return "partial";
    if (status.includes("SẴN")) return "avail";
    return "";
  }

  // ── Vue App ─────────────────────────────────────────────────
  const App = {
    data() {
      return {
        // View: "list" | "workspace"
        view: "list",

        // Project list
        projects: [],
        loadingProjects: false,

        // New project modal
        showNewModal: false,
        newForm: { project_name: "", customer: "", custom_app_name: "", selected_apps: [] },
        availableApps: [],

        // Current project
        project: null,

        // Chat
        messages: [],       // [{role, content, type}]
        inputText: "",
        isLoading: false,
        streamingText: "",  // text đang stream

        // Context panel
        activeTab: "requirements",   // requirements | context

        // Upload
        isDragging: false,
        uploadedFileName: "",
      };
    },

    computed: {
      clarifiedCount() {
        if (!this.project) return 0;
        return (this.project.requirements || []).filter((r) => r.clarified).length;
      },
      totalReq() {
        return (this.project?.requirements || []).length;
      },
      progressPct() {
        if (!this.totalReq) return 0;
        return Math.round((this.clarifiedCount / this.totalReq) * 100);
      },
      purchasedApps() {
        return (this.project?.base_apps || []).filter((a) => a.included).map((a) => a.app_name);
      },
    },

    async mounted() {
      await this.loadProjects();
      await this.loadCatalog();
    },

    methods: {
      // ── Project List ──────────────────────────────────────────
      async loadProjects() {
        this.loadingProjects = true;
        try {
          this.projects = await api.call("get_projects");
        } finally {
          this.loadingProjects = false;
        }
      },

      async loadCatalog() {
        try {
          this.availableApps = await api.call("get_catalog");
        } catch (_) {}
      },

      async deleteProject(name) {
        frappe.confirm("Xóa dự án này và toàn bộ lịch sử phân tích/trao đổi?", async () => {
          await api.call("delete_project", { project_name: name });
          frappe.show_alert({ message: "Đã xóa dự án", indicator: "red" });
          await this.loadProjects();
          if (this.project && this.project.name === name) {
            this.project = null;
            this.view = "list";
          }
        });
      },

      async openProject(name) {
        this.project = await api.call("get_project", { project_name: name });
        this.messages = await api.call("get_chat_history", { project_name: name });
        this.view = "workspace";
        this.$nextTick(() => this.scrollBottom());
      },

      // ── New Project ───────────────────────────────────────────
      toggleApp(appName) {
        const idx = this.newForm.selected_apps.indexOf(appName);
        if (idx === -1) this.newForm.selected_apps.push(appName);
        else this.newForm.selected_apps.splice(idx, 1);
      },

      isAppSelected(appName) {
        return this.newForm.selected_apps.includes(appName);
      },

      async createProject() {
        if (!this.newForm.project_name.trim()) {
          frappe.msgprint("Vui lòng nhập tên dự án");
          return;
        }
        const r = await api.call("create_project", {
          project_name: this.newForm.project_name,
          customer: this.newForm.customer,
          custom_app_name: this.newForm.custom_app_name,
          base_apps: JSON.stringify(this.newForm.selected_apps),
        });
        this.showNewModal = false;
        this.newForm = { project_name: "", customer: "", custom_app_name: "", selected_apps: [] };
        await this.openProject(r.name);
      },

      // ── File Upload ───────────────────────────────────────────
      handleDrop(e) {
        e.preventDefault();
        this.isDragging = false;
        const file = e.dataTransfer.files[0];
        if (file) this.uploadFile(file);
      },

      triggerFileInput() {
        this.$refs.fileInput.click();
      },

      handleFileChange(e) {
        const file = e.target.files[0];
        if (file) this.uploadFile(file);
      },

      async uploadFile(file) {
        const allowed = ["application/pdf",
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          "application/msword"];
        if (!allowed.includes(file.type) && !file.name.match(/\.(pdf|docx|doc)$/i)) {
          frappe.msgprint("Chỉ hỗ trợ file PDF và DOCX");
          return;
        }
        this.isLoading = true;
        this.uploadedFileName = file.name;
        try {
          const formData = new FormData();
          formData.append("file", file, file.name);
          formData.append("is_private", "0");
          formData.append("doctype", "SRS Project");
          formData.append("docname", this.project.name);

          const headers = {};
          if (frappe.csrf_token) {
            headers["X-Frappe-CSRF-Token"] = frappe.csrf_token;
          }

          const resp = await fetch("/api/method/upload_file", {
            method: "POST",
            body: formData,
            credentials: "same-origin",
            headers,
          });
          if (!resp.ok) {
            const txt = await resp.text();
            throw new Error("Upload failed with status " + resp.status + ": " + txt);
          }
          const r = await resp.json();
          const fileUrl = (r.message && r.message.file_url) || r.file_url;
          const extracted = await api.call("extract_file_text", {
            project_name: this.project.name,
            file_url: fileUrl,
          });
          if (extracted.status === "ok") {
            // Không tự đổ text vào ô nhập nữa, chỉ báo đã đọc file.
            frappe.show_alert({ message: `Đã đọc file: ${file.name}`, indicator: "green" });
          } else {
            frappe.msgprint("Lỗi đọc file: " + (extracted.message || "Không xác định"));
          }
        } catch (e) {
          frappe.msgprint("Lỗi upload: " + e);
        } finally {
          this.isLoading = false;
        }
      },

      // ── Chat ─────────────────────────────────────────────────
      async sendMessage() {
        const text = this.inputText.trim();
        if (!text || this.isLoading) return;

        this.messages.push({ role: "user", content: text });
        this.inputText = "";
        this.isLoading = true;
        this.$nextTick(() => this.scrollBottom());

        try {
          const r = await api.call("chat", {
            project_name: this.project.name,
            message: text,
          });
          if (r.status === "ok") {
            this.messages.push({ role: "assistant", content: r.message });
            this.$nextTick(() => this.scrollBottom());
            // Reload requirements nếu Claude có update
            await this.refreshRequirements();
          } else {
            frappe.msgprint("Lỗi: " + r.message);
          }
        } finally {
          this.isLoading = false;
        }
      },

      async analyze() {
        if (!this.project.requirement_text && !this.project.requirement_files) {
          frappe.msgprint("Vui lòng nhập yêu cầu hoặc upload file trước");
          return;
        }
        this.isLoading = true;
        this.messages.push({
          role: "system-info",
          content: "🔍 Đang phân tích tài liệu yêu cầu...",
        });
        this.$nextTick(() => this.scrollBottom());

        try {
          const r = await api.call("analyze", { project_name: this.project.name });
          if (r.status === "ok") {
            this.messages.push({ role: "assistant", content: r.message });
            await this.refreshProject();
            this.$nextTick(() => this.scrollBottom());
            frappe.show_alert({ message: `Đã phân tích ${r.requirements?.length || 0} yêu cầu`, indicator: "green" });
          } else {
            frappe.msgprint("Lỗi phân tích: " + r.message);
          }
        } finally {
          this.isLoading = false;
        }
      },

      async generateSRS() {
        if (!this.totalReq) {
          frappe.msgprint("Chưa có yêu cầu nào được phân tích");
          return;
        }
        frappe.confirm("Sinh file SRS từ kết quả phân tích hiện tại?", async () => {
          this.isLoading = true;
          this.messages.push({ role: "system-info", content: "📄 Đang sinh file SRS..." });
          this.$nextTick(() => this.scrollBottom());
          try {
            const r = await api.call("generate_srs", { project_name: this.project.name });
            if (r.status === "ok") {
              this.messages.push({
                role: "assistant",
                content: `✅ File SRS đã được tạo thành công!\n\n📥 [Tải xuống SRS DOCX](${r.file_url})`,
              });
              this.project.output_srs = r.file_url;
              this.project.status = "Completed";
              this.$nextTick(() => this.scrollBottom());
            } else {
              frappe.msgprint("Lỗi: " + r.message);
            }
          } finally {
            this.isLoading = false;
          }
        });
      },

      async clearChat() {
        frappe.confirm("Xóa toàn bộ lịch sử chat và phân tích lại từ đầu?", async () => {
          await api.call("clear_chat", { project_name: this.project.name });
          this.messages = [];
          await this.refreshProject();
          frappe.show_alert({ message: "Đã xóa lịch sử chat", indicator: "blue" });
        });
      },

      // ── Requirement inline edit ───────────────────────────────
      async updateReqStatus(req, newStatus) {
        req.gap_status = newStatus;
        await api.call("update_requirement_item", {
          project_name: this.project.name,
          req_id: req.req_id,
          field: "gap_status",
          value: newStatus,
        });
      },

      async toggleClarified(req) {
        req.clarified = req.clarified ? 0 : 1;
        await api.call("update_requirement_item", {
          project_name: this.project.name,
          req_id: req.req_id,
          field: "clarified",
          value: req.clarified ? "1" : "0",
        });
      },

      // ── Quick question shortcuts ──────────────────────────────
      askClarify(req) {
        this.inputText = `Làm rõ yêu cầu "${req.req_id} – ${req.requirement_text.substring(0, 60)}...": `;
        this.$refs.chatInput?.focus();
      },

      // ── Helpers ──────────────────────────────────────────────
      async refreshProject() {
        this.project = await api.call("get_project", { project_name: this.project.name });
      },

      async refreshRequirements() {
        const updated = await api.call("get_project", { project_name: this.project.name });
        this.project.requirements = updated.requirements;
        this.project.status = updated.status;
      },

      scrollBottom() {
        const el = this.$refs.chatMessages;
        if (el) el.scrollTop = el.scrollHeight;
      },

      handleKeydown(e) {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          this.sendMessage();
        }
      },

      mdToHtml,
      gapClass,

      statusLabel(s) {
        const map = { Draft: "Nháp", Analyzing: "Đang phân tích", Clarifying: "Làm rõ", Completed: "Hoàn thành" };
        return map[s] || s;
      },
    },

    // ── Template ──────────────────────────────────────────────
    template: `
<div id="reqpilot-root">

  <!-- ══ PROJECT LIST VIEW ════════════════════════════════════ -->
    <div v-if="view === 'list'" class="rp-project-list">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
      <h4 style="margin:0">🧠 MBWNext – Support SRS for BA</h4>
      <button class="rp-sidebar-btn primary" style="width:auto;padding:8px 16px"
              @click="showNewModal=true">+ Dự án mới</button>
    </div>

    <div v-if="loadingProjects" style="text-align:center;padding:40px;color:#ffffff;text-shadow:0 1px 4px rgba(15,23,42,0.9)">
      Đang tải...
    </div>
    <div v-else-if="!projects.length" style="text-align:center;padding:60px 40px;color:#ffffff;text-shadow:0 1px 4px rgba(15,23,42,0.9)">
      <p style="margin-bottom:10px">
        <img src="/assets/mbwnext_localization/logo.png"
             alt="MBWNext"
             style="height:40px;filter:drop-shadow(0 5px 14px rgba(15,23,42,0.8));">
      </p>
      <p style="font-size:14px;font-weight:600;margin-bottom:4px">Chưa có dự án nào</p>
      <p style="font-size:12px;opacity:0.9">Nhấn <strong>“+ Dự án mới”</strong> để bắt đầu.</p>
    </div>
    <div v-else>
      <div v-for="p in projects" :key="p.name"
           class="rp-project-card" @click="openProject(p.name)">
        <div>
          <div class="rp-project-card-title">{{ p.project_name }}</div>
          <div class="rp-project-card-meta">
            {{ p.customer || 'Chưa có khách hàng' }}
            · {{ p.custom_app_name || '' }}
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:6px">
          <span :class="'rp-status-badge ' + (p.status||'draft').toLowerCase()">
            {{ statusLabel(p.status) }}
          </span>
          <button
            @click.stop="deleteProject(p.name)"
            style="border:none;background:transparent;color:#ef4444;font-size:14px;cursor:pointer;padding:2px 4px"
            title="Xóa dự án">
            🗑
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- ══ WORKSPACE VIEW ═══════════════════════════════════════ -->
  <div v-else class="rp-workspace">

    <!-- ── Sidebar ───────────────────────────────────────────── -->
    <div class="rp-sidebar">
      <div class="rp-sidebar-section">
        <button class="rp-sidebar-btn" @click="view='list'; project=null">
          ← Danh sách dự án
        </button>
      </div>

      <!-- Project info -->
      <div class="rp-sidebar-section" v-if="project">
        <h6>DỰ ÁN</h6>
        <div class="rp-project-name">{{ project.project_name }}</div>
        <div class="rp-project-customer">{{ project.customer }}</div>
        <span :class="'rp-status-badge ' + (project.status||'draft').toLowerCase()">
          {{ statusLabel(project.status) }}
        </span>
        <div style="margin-top:8px;font-size:11px;color:#718096">
          App: <strong>{{ project.custom_app_name || 'N/A' }}</strong>
        </div>
      </div>

      <!-- Base apps -->
      <div class="rp-sidebar-section" v-if="purchasedApps.length">
        <h6>BASE APPS</h6>
        <span v-for="app in purchasedApps" :key="app" class="rp-app-tag">
          {{ app.replace('mbwnext_advanced_','').replace('mbwnext_','') }}
        </span>
      </div>

      <!-- Progress -->
      <div class="rp-sidebar-section" v-if="totalReq">
        <h6>TIẾN ĐỘ LÀM RÕ</h6>
        <div class="rp-progress">
          <div class="rp-progress-bar">
            <div class="rp-progress-bar-fill" :style="{width: progressPct + '%'}"></div>
          </div>
          <div class="rp-progress-text">{{ clarifiedCount }}/{{ totalReq }} yêu cầu đã làm rõ</div>
        </div>
      </div>

      <!-- Upload -->
      <div class="rp-sidebar-section">
        <h6>TÀI LIỆU YÊU CẦU</h6>
        <div class="rp-upload-area"
             :class="{dragover: isDragging}"
             @dragover.prevent="isDragging=true"
             @dragleave="isDragging=false"
             @drop="handleDrop"
             @click="triggerFileInput">
          <p>📎 Kéo thả hoặc click để upload</p>
          <p style="font-size:11px">PDF / DOCX</p>
          <p v-if="uploadedFileName" style="font-size:11px;color:#3182ce;font-weight:600">
            ✓ {{ uploadedFileName }}
          </p>
        </div>
        <input ref="fileInput" type="file" accept=".pdf,.docx,.doc"
               style="display:none" @change="handleFileChange">
        <textarea v-if="project"
          v-model="project.requirement_text"
          placeholder="Hoặc nhập/paste yêu cầu trực tiếp..."
          style="width:100%;font-size:13px;line-height:1.5;border:1px solid #e2e8f0;border-radius:6px;
                 padding:8px 10px;resize:vertical;min-height:180px;outline:none;
                 font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,'Liberation Mono','Courier New',monospace">
        </textarea>
      </div>

      <!-- Actions -->
      <div style="display:flex;flex-direction:column;gap:6px">
        <button class="rp-sidebar-btn primary" @click="analyze" :disabled="isLoading">
          🔍 Phân tích yêu cầu
        </button>
        <button class="rp-sidebar-btn success" @click="generateSRS" :disabled="isLoading||!totalReq">
          📄 Sinh file SRS
        </button>
        <a v-if="project && project.output_srs"
           class="rp-sidebar-btn"
           :href="project.output_srs"
           target="_blank"
           rel="noopener">
          📥 Tải SRS
        </a>
        <button class="rp-sidebar-btn danger" @click="clearChat" :disabled="isLoading">
          🗑 Xóa & làm lại
        </button>
      </div>
    </div>

    <!-- ── Chat Area ──────────────────────────────────────────── -->
    <div class="rp-chat-area">
      <div class="rp-chat-header">
        <h5>💬 Hội thoại BA ↔ AI</h5>
        <span style="font-size:11px;color:#718096">
          {{ messages.filter(m=>m.role==='user').length }} tin nhắn
        </span>
      </div>

      <!-- Messages -->
      <div class="rp-chat-messages" ref="chatMessages">
        <!-- Welcome -->
        <div v-if="!messages.length" style="text-align:center;padding:40px;color:#718096">
          <p style="font-size:28px">🤖</p>
          <p style="font-size:14px;font-weight:600">Xin chào! Tôi là BA AI của MBWNext.</p>
          <p style="font-size:12px">Upload file yêu cầu hoặc nhập text rồi nhấn<br>
            <strong>"Phân tích yêu cầu"</strong> để bắt đầu.</p>
        </div>

        <!-- Message list -->
        <template v-for="(msg, i) in messages" :key="i">
          <!-- System info -->
          <div v-if="msg.role==='system-info'"
               style="text-align:center;font-size:12px;color:#718096;padding:4px 0">
            {{ msg.content }}
          </div>
          <!-- User / Assistant -->
          <div v-else :class="'rp-msg ' + msg.role">
            <div class="rp-msg-avatar">
              {{ msg.role === 'user' ? 'BA' : 'AI' }}
            </div>
            <div class="rp-msg-bubble" v-html="mdToHtml(msg.content)"></div>
          </div>
        </template>

        <!-- Typing indicator -->
        <div v-if="isLoading" class="rp-typing">
          <span></span><span></span><span></span>
        </div>
      </div>

      <!-- Input -->
      <div class="rp-chat-input">
        <textarea ref="chatInput"
          v-model="inputText"
          placeholder="Nhập câu hỏi hoặc thông tin làm rõ... (Enter để gửi, Shift+Enter xuống dòng)"
          @keydown="handleKeydown"
          rows="1">
        </textarea>
        <button class="rp-send-btn" @click="sendMessage" :disabled="isLoading||!inputText.trim()">
          Gửi ↵
        </button>
      </div>
    </div>

    <!-- ── Context Panel ──────────────────────────────────────── -->
    <div class="rp-context-panel">
      <div class="rp-context-tabs">
        <div :class="'rp-context-tab '+(activeTab==='requirements'?'active':'')"
             @click="activeTab='requirements'">
          Yêu cầu ({{ totalReq }})
        </div>
        <div :class="'rp-context-tab '+(activeTab==='context'?'active':'')"
             @click="activeTab='context'">
          Context
        </div>
      </div>

      <div class="rp-context-body">
        <!-- Requirements tab -->
        <template v-if="activeTab==='requirements'">
          <div v-if="!totalReq" style="text-align:center;padding:20px;color:#718096;font-size:12px">
            Chưa có yêu cầu nào.<br>Nhấn "Phân tích yêu cầu" để bắt đầu.
          </div>
          <div v-for="req in project.requirements" :key="req.req_id"
               class="rp-req-row" @click="askClarify(req)">
            <div class="rp-req-id">{{ req.req_id }}</div>
            <div class="rp-req-text">{{ req.requirement_text }}</div>
            <div class="rp-req-meta">
              <span v-if="req.gap_status" :class="'rp-badge ' + gapClass(req.gap_status)">
                {{ req.gap_status }}
              </span>
              <span v-if="req.mapped_app" class="rp-badge app">
                {{ req.mapped_app.replace('mbwnext_','') }}
              </span>
              <span v-if="req.effort_days" style="font-size:10px;color:#718096">
                {{ req.effort_days }}d
              </span>
            </div>
            <div style="margin-top:4px;display:flex;gap:6px;align-items:center">
              <label style="font-size:10px;cursor:pointer;display:flex;align-items:center;gap:4px">
                <input type="checkbox" class="rp-checkbox" :checked="req.clarified"
                       @click.stop="toggleClarified(req)">
                Đã làm rõ
              </label>
              <span v-if="req.priority" style="font-size:10px;color:#718096">
                Ưu tiên: {{ req.priority }}
              </span>
            </div>
          </div>
        </template>

        <!-- Context tab -->
        <template v-if="activeTab==='context'">
          <div style="font-size:12px">
            <p style="font-weight:600;margin-bottom:8px">Base Apps trong context:</p>
            <div v-for="app in purchasedApps" :key="app"
                 style="padding:6px 8px;background:white;border:1px solid #e2e8f0;
                        border-radius:4px;margin-bottom:4px;font-size:11px">
              {{ app }}
            </div>
            <p style="font-weight:600;margin:12px 0 8px">Thông tin dự án:</p>
            <table style="width:100%;font-size:11px;border-collapse:collapse">
              <tr><td style="padding:3px;color:#718096">Tên:</td>
                  <td style="padding:3px;font-weight:600">{{ project?.project_name }}</td></tr>
              <tr><td style="padding:3px;color:#718096">Khách hàng:</td>
                  <td style="padding:3px">{{ project?.customer }}</td></tr>
              <tr><td style="padding:3px;color:#718096">Custom App:</td>
                  <td style="padding:3px;font-family:monospace">{{ project?.custom_app_name }}</td></tr>
              <tr><td style="padding:3px;color:#718096">Trạng thái:</td>
                  <td style="padding:3px">{{ statusLabel(project?.status) }}</td></tr>
              <tr><td style="padding:3px;color:#718096">Tổng YC:</td>
                  <td style="padding:3px">{{ totalReq }}</td></tr>
            </table>
          </div>
        </template>
      </div>
    </div>
  </div>

  <!-- ══ NEW PROJECT MODAL ════════════════════════════════════ -->
  <div v-if="showNewModal" class="rp-modal-overlay" @click.self="showNewModal=false">
    <div class="rp-modal">
      <h5>➕ Tạo dự án mới</h5>

      <div class="rp-form-group">
        <label>Tên dự án *</label>
        <input v-model="newForm.project_name" placeholder="VD: RTG – Phase 1">
      </div>
      <div class="rp-form-group">
        <label>Khách hàng</label>
        <input v-model="newForm.customer" placeholder="VD: Công ty Rượu thế giới">
      </div>
      <div class="rp-form-group">
        <label>Custom App Name</label>
        <input v-model="newForm.custom_app_name" placeholder="VD: mbwnext_rtg">
      </div>

      <div class="rp-form-group">
        <label>Base Apps khách hàng mua</label>
        <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;margin-top:4px">
          <label v-for="app in availableApps" :key="app.app_name"
                 style="display:flex;align-items:center;gap:6px;cursor:pointer;
                        padding:6px 10px;border:1px solid #e2e8f0;border-radius:6px;font-size:12px"
                 :style="isAppSelected(app.app_name)
                   ? 'background:#EEF2FF;border-color:#6366f1;color:#1D4ED8;font-weight:600'
                   : 'background:white'">
            <input type="checkbox" class="rp-checkbox"
                   :checked="isAppSelected(app.app_name)"
                   @change="toggleApp(app.app_name)">
            {{ app.app_title || app.app_name }}
          </label>
        </div>
      </div>

      <div class="rp-modal-actions">
        <button class="rp-sidebar-btn" @click="showNewModal=false">Hủy</button>
        <button class="rp-sidebar-btn primary" style="width:auto"
                @click="createProject">Tạo dự án</button>
      </div>
    </div>
  </div>

</div>
    `,
  };

  // ── Mount khi Vue sẵn sàng ────────────────────────────────────
  function mountApp() {
    if (typeof Vue === "undefined") {
      // Load Vue 3 CDN
      const script = document.createElement("script");
      script.src = "https://unpkg.com/vue@3/dist/vue.global.prod.js";
      script.onload = () => {
        window.ReqPilotApp = Vue.createApp(App);
        if (document.getElementById("reqpilot-root")) {
          window.ReqPilotApp.mount("#reqpilot-root");
        }
      };
      document.head.appendChild(script);
    } else {
      window.ReqPilotApp = Vue.createApp(App);
    }
  }

  mountApp();
})();
