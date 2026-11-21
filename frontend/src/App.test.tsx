import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { App } from "./App";
import {
  addBoqItem,
  confirmExtractionDrawingUnit,
  createBoqSheet,
  createProject,
  createTask,
  deleteProviderApiKey,
  enhanceReviewReportAi,
  exportBoqDeliverables,
  extractProjectFile,
  generateReviewReport,
  getDeliverableDownloadUrl,
  getExtractionCapabilities,
  getExtractionDetail,
  getExtractionPageImageUrl,
  getFileDownloadUrl,
  getProject,
  getProviderSettings,
  getSupportedExtensions,
  getTaskDetail,
  listDeliverables,
  listFileExtractions,
  listProjectBoqSheets,
  listProjectFiles,
  listProjects,
  listResearchRuns,
  listTasks,
  refreshProviderModels,
  rerunBoqChecks,
  runControlledResearch,
  saveProviderApiKey,
  summarizeDrawingVision,
  testProviderConnection,
  updateBoqItem,
  updateBoqSheet,
  updateProviderSettings,
  uploadProjectFiles,
} from "./api";
import { AssignmentsView } from "./components/AssignmentsView";
import { BoqView } from "./components/BoqView";
import { DeliverablesView } from "./components/DeliverablesView";
import { ProjectFilesPanel } from "./components/ProjectFilesPanel";
import { ProjectWorkspaceView } from "./components/ProjectWorkspaceView";
import { ProviderSettingsView } from "./components/ProviderSettingsView";
import { ResearchView } from "./components/ResearchView";
import type {
  BoqDetailOut,
  DeliverableOut,
  ExtractionCapabilitiesOut,
  FileExtractionDetailOut,
  ProjectDetail,
  ProjectFileOut,
  ProjectSummary,
  ProviderSettingsOut,
  ResearchRunDetailOut,
  ResearchRunSummaryOut,
  ReviewReportDetailOut,
  TaskDetailOut,
  TaskSummaryOut,
} from "./types";

const TWELVE_FOLDERS = [
  "01_Input_Documents",
  "02_Original_Drawings",
  "03_Analysis",
  "04_Engineering_Calculations",
  "05_Design_Drawings",
  "06_BOQ",
  "07_Technical_Specifications",
  "08_Reports",
  "09_Comparisons",
  "10_Final_Deliverables",
  "11_References",
  "12_Revision_History",
];

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App Step 02 project workspace UI", () => {
  it("renders Arabic RTL layout, project form, and Preliminary badge without mock projects", () => {
    const html = renderToStaticMarkup(<App initialLang="ar" />);
    expect(html).toContain('dir="rtl"');
    expect(html).toContain('lang="ar"');
    expect(html).toContain("إنشاء مشروع هندسي جديد");
    expect(html).toContain("المشاريع الهندسية المحفوظة (0)");
    expect(html).toContain("Preliminary");
  });

  it("renders English LTR layout when switched", () => {
    const html = renderToStaticMarkup(<App initialLang="en" />);
    expect(html).toContain('dir="ltr"');
    expect(html).toContain('lang="en"');
    expect(html).toContain("Create Engineering Project");
    expect(html).toContain("Persisted Engineering Projects (0)");
  });

  it("renders Arabic project list item and opened project page with all 12 workspace folders", () => {
    const summary: ProjectSummary = {
      id: "p-1",
      code: "PRJ-01",
      name: "مستشفى طرابلس التعليمي",
      name_en: "Tripoli Teaching Hospital",
      client_name: "وزارة الصحة",
      location: "طرابلس",
      description: "مشروع تجريبي للتحقق من الواجهة",
      discipline_scope: "Multidisciplinary",
      status: "active",
      classification: "Preliminary",
      workspace_slug: "مستشفى_طرابلس_التعليمي_12345678",
      created_at: "2026-11-18T19:00:00Z",
      updated_at: "2026-11-18T19:00:00Z",
    };
    const detail: ProjectDetail = {
      ...summary,
      workspace_exists: true,
      folders: TWELVE_FOLDERS.map((folderName) => ({
        name: folderName,
        relative_path: `${summary.workspace_slug}/${folderName}`,
        exists: true,
      })),
    };

    const listHtml = renderToStaticMarkup(
      <ProjectWorkspaceView lang="ar" initialProjects={[summary]} />
    );
    expect(listHtml).toContain("مستشفى طرابلس التعليمي");
    expect(listHtml).toContain("PRJ-01");
    expect(listHtml).toContain("فتح المشروع");

    const detailHtml = renderToStaticMarkup(
      <ProjectWorkspaceView lang="ar" initialOpenedProject={detail} />
    );
    expect(detailHtml).toContain("مستشفى طرابلس التعليمي");
    expect(detailHtml).toContain("موجود على القرص");
    for (const folderName of TWELVE_FOLDERS) {
      expect(detailHtml).toContain(folderName);
    }
  });
});

describe("Project API client", () => {
  it("sends POST /api/projects, GET /api/projects, GET /api/projects/{id}, and parses errors", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: "p-1", name: "مشروع" }), { status: 201 })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ projects: [], total: 0, classification: "Preliminary" }), {
          status: 200,
        })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: "p-1", folders: [] }), { status: 200 })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Project code already exists: HOSP-01" }), {
          status: 409,
        })
      );

    vi.stubGlobal("fetch", fetchMock);

    await createProject({ name: "مشروع", code: "PRJ-1" });
    await listProjects();
    await getProject("p-1");
    await expect(createProject({ name: "مشروع آخر", code: "HOSP-01" })).rejects.toThrow(
      "Project code already exists: HOSP-01"
    );

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/projects",
      expect.objectContaining({ method: "POST" })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/projects", undefined);
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/projects/p-1", undefined);
  });
});

describe("Step 03 ProjectFilesPanel & file API client", () => {
  it("renders Arabic RTL dropzone, file metadata columns, and expanded version history", () => {
    const sampleHashV1 = "1111111111112222222222223333333333334444444444445555555555556666";
    const sampleHashV2 = "aaaaaabbbbbbccccccddddddeeeeeeffffff0000001111112222223333334444";
    const sampleFile: ProjectFileOut = {
      id: "file-1",
      project_id: "p-1",
      folder_name: "01_Input_Documents",
      original_filename: "تقرير_تربة.pdf",
      stored_relative_path: "12_Revision_History/file-1/v2_تقرير_تربة.pdf",
      mime_type: "application/pdf",
      extension: ".pdf",
      size_bytes: 2048,
      sha256: sampleHashV2,
      is_original: true,
      status: "registered",
      classification: "Preliminary",
      current_version: 2,
      created_at: "2026-11-18T22:00:00+00:00",
      updated_at: "2026-11-18T22:05:00+00:00",
      versions: [
        {
          id: "ver-2",
          file_id: "file-1",
          version_number: 2,
          stored_relative_path: "12_Revision_History/file-1/v2_تقرير_تربة.pdf",
          size_bytes: 2048,
          sha256: sampleHashV2,
          change_note: "Re-uploaded updated file (v2); original preserved",
          created_by: "owner",
          created_at: "2026-11-18T22:05:00+00:00",
        },
        {
          id: "ver-1",
          file_id: "file-1",
          version_number: 1,
          stored_relative_path: "01_Input_Documents/تقرير_تربة.pdf",
          size_bytes: 1024,
          sha256: sampleHashV1,
          change_note: "Original file upload (read-only)",
          created_by: "owner",
          created_at: "2026-11-18T22:00:00+00:00",
        },
      ],
    };

    const html = renderToStaticMarkup(
      <ProjectFilesPanel
        lang="ar"
        projectId="p-1"
        initialFiles={[sampleFile]}
        initialExpandedFileId="file-1"
      />
    );

    expect(html).toContain("اسحب وأفلت ملفات المشروع هنا");
    expect(html).toContain("تقرير_تربة.pdf");
    expect(html).toContain("01_Input_Documents");
    expect(html).toContain("2.0 KB");
    expect(html).toContain("aaaaaabbbbbb…334444");
    expect(html).toContain("الأصل للقراءة فقط");
    expect(html).toContain("سجل الإصدارات الثابت");
    expect(html).toContain("v2");
    expect(html).toContain("أصل v1");
    expect(html).toContain('/api/files/file-1/download?version=1');
  });

  it("calls file upload, list, supported extensions, and formats versioned download URLs", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ project_id: "p-1", created_count: 1, new_version_count: 0, duplicate_count: 0, items: [] }), {
          status: 201,
        })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ project_id: "p-1", files: [], total: 0, classification: "Preliminary" }), {
          status: 200,
        })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ extensions: [], explicitly_unsupported_examples: [], max_upload_size_bytes: 52428800, max_files_per_upload: 25 }), {
          status: 200,
        })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Path traversal or directory separators rejected" }), {
          status: 400,
        })
      );

    vi.stubGlobal("fetch", fetchMock);

    const file = new File([new Uint8Array([1, 2, 3])], "brief.pdf", { type: "application/pdf" });
    await uploadProjectFiles("p-1", [file]);
    await listProjectFiles("p-1");
    await getSupportedExtensions();
    await expect(uploadProjectFiles("p-1", [file])).rejects.toThrow(
      "Path traversal or directory separators rejected"
    );

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/projects/p-1/files",
      expect.objectContaining({ method: "POST" })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/projects/p-1/files", undefined);
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/files/supported-extensions", undefined);
    expect(getFileDownloadUrl("file-1")).toBe("/api/files/file-1/download");
    expect(getFileDownloadUrl("file-1", 1)).toBe("/api/files/file-1/download?version=1");
  });
});

describe("Step 04 ProviderSettingsView & settings API client", () => {
  it("renders Arabic RTL provider settings screen with masked password input and notice", () => {
    const sampleSettings: ProviderSettingsOut = {
      active_provider: "gemini",
      available_providers: [
        {
          id: "gemini",
          name: "Google Gemini (Official google-genai SDK)",
          models: [
            { id: "gemini-3.8-flash", label: "Gemini 3.8 Flash", tier: "fast" },
            { id: "gemini-3.5-flash-lite", label: "Gemini 3.5 Flash-Lite", tier: "fast" },
            { id: "gemini-4-argon", label: "Gemini 4 Argon", tier: "deep" },
          ],
        },
      ],
      models: { fast: "gemini-3.8-flash", deep: "gemini-4-argon" },
      usage_limits: {
        daily_request_limit: 200,
        daily_token_limit: 500000,
        monthly_request_limit: 3000,
        monthly_token_limit: 5000000,
        max_output_tokens: 8192,
      },
      daily_usage: {
        date_utc: "2026-11-19",
        requests: 2,
        prompt_tokens: 120,
        output_tokens: 45,
        total_tokens: 165,
      },
      monthly_usage: {
        month_utc: "2026-11",
        requests: 12,
        prompt_tokens: 900,
        output_tokens: 350,
        total_tokens: 1250,
      },
      api_key_configured: true,
      credential_backend: "WinVaultKeyring",
      last_connection_check: {
        status: "connected",
        checked_at: "2026-11-19T00:00:00Z",
        model: "gemini-3.8-flash",
        message: "Connected cleanly to gemini-3.8-flash.",
        latency_ms: 95,
      },
      models_source: "live_api",
      models_refreshed_at: "2026-11-19T00:00:00Z",
      model_warning:
        "Configured model 'gemini-2.5-flash' was not found in the latest live model list.",
      consumer_subscription_notice:
        "Consumer Gemini subscription does not include Gemini API access.",
      classification: "Preliminary",
    };

    const shellHtml = renderToStaticMarkup(<App initialLang="ar" initialTab="settings" />);
    expect(shellHtml).toContain('dir="rtl"');
    expect(shellHtml).toContain("إعدادات Gemini والمزودين");
    expect(shellHtml).toContain('type="password"');
    expect(shellHtml).toContain("اشتراك Gemini الاستهلاكي");

    const settingsHtml = renderToStaticMarkup(
      <ProviderSettingsView lang="ar" initialSettings={sampleSettings} />
    );
    expect(settingsHtml).toContain("محفوظ بأمان (••••••••••••)");
    expect(settingsHtml).toContain("WinVaultKeyring");
    expect(settingsHtml).toContain("gemini-3.8-flash");
    expect(settingsHtml).toContain("gemini-3.5-flash-lite");
    expect(settingsHtml).toContain("gemini-4-argon");
    expect(settingsHtml).toContain("تحديث النماذج الحية (generateContent)");
    expect(settingsHtml).toContain("قائمة حية من Gemini API");
    expect(settingsHtml).toContain("<select");
    expect(settingsHtml).toContain('type="text"');
    expect(settingsHtml).toContain("was not found in the latest live model list.");
    expect(settingsHtml).toContain("12 / 3000");
    expect(settingsHtml).toContain("1250 / 5000000");
    expect(settingsHtml).toContain("اختبار الاتصال بـ Gemini");
    expect(settingsHtml).toContain("متصل بنجاح");
  });

  it("calls settings endpoints cleanly without exposing secrets", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ active_provider: "gemini", api_key_configured: false }), {
          status: 200,
        })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ active_provider: "gemini", api_key_configured: true }), {
          status: 200,
        })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ active_provider: "gemini", api_key_configured: true }), {
          status: 200,
        })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ connected: true, model: "gemini-3.8-flash" }), {
          status: 200,
        })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ active_provider: "gemini", models_source: "live_api" }), {
          status: 200,
        })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ active_provider: "gemini", api_key_configured: false }), {
          status: 200,
        })
      );

    vi.stubGlobal("fetch", fetchMock);

    await getProviderSettings();
    await saveProviderApiKey("mock-nonkey-credential-value");
    await updateProviderSettings({
      active_provider: "gemini",
      models: { fast: "gemini-3.8-flash", deep: "gemini-4-argon" },
      usage_limits: {
        daily_request_limit: 100,
        daily_token_limit: 250000,
        monthly_request_limit: 2000,
        monthly_token_limit: 3000000,
        max_output_tokens: 4096,
      },
    });
    await testProviderConnection("fast");
    await refreshProviderModels();
    await deleteProviderApiKey();

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/settings/provider", undefined);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/settings/provider/api-key",
      expect.objectContaining({ method: "PUT" })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/settings/provider",
      expect.objectContaining({ method: "PUT" })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/settings/provider/test",
      expect.objectContaining({ method: "POST" })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      "/api/settings/provider/models/refresh",
      expect.objectContaining({ method: "POST" })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      6,
      "/api/settings/provider/api-key",
      expect.objectContaining({ method: "DELETE" })
    );
  });
});

describe("Step 05 AssignmentsView & Task Engine API client", () => {
  it("renders Arabic RTL New Assignment form, Task History, Orchestrator v0 JSON, and failed task banner", () => {
    const sampleProjects: ProjectSummary[] = [
      {
        id: "proj-05",
        code: "CLN-05",
        name: "عيادة طرابلس",
        name_en: "Tripoli Clinic",
        client_name: "Ministry",
        location: "Tripoli",
        description: null,
        discipline_scope: "Architectural",
        status: "active",
        classification: "Preliminary",
        workspace_slug: "cln-05",
        created_at: "2026-11-19T00:00:00Z",
        updated_at: "2026-11-19T00:00:00Z",
      },
    ];

    const selectedTask: TaskDetailOut = {
      id: "task-05-1",
      project_id: "proj-05",
      project_code: "CLN-05",
      project_name: "عيادة طرابلس",
      title: "مراجعة المخطط المعماري للعيادة",
      prompt: "مراجعة المخطط المعماري للعيادة والتحقق من المتطلبات.",
      task_type: "assignment",
      status: "awaiting_clarification",
      classification: "Preliminary",
      complexity: "fast",
      provider_name: "gemini",
      model_name: "gemini-3.8-flash",
      plan_summary: "إعادة صياغة المهمة",
      result_summary: "Architectural | 1 deliverables | clarification_needed=True",
      error_message: null,
      attached_file_ids: ["file-01"],
      structured_output: {
        language_detected: "ar",
        restated_assignment: "مراجعة المخطط المعماري للعيادة وتحديد الملاحظات الأولية.",
        primary_discipline: "Architectural",
        secondary_disciplines: ["Fire & Life Safety"],
        expected_deliverables: ["تقرير مراجعة معمارية"],
        input_files: [
          { filename: "clinic.pdf", role: "المخطط المعماري", status: "attached" },
        ],
        applicable_standards_to_verify: ["NFPA 101 Life Safety Code"],
        missing_information: ["السعة التصميمية للعيادة"],
        assumptions: ["التحقق من سعة العيادة في الخطوة اللاحقة"],
        clarification_needed: true,
        clarifying_questions: ["ما هي السعة التصميمية المتوقعة للمرضى؟"],
        recommended_next_steps: ["استخراج بيانات ملف clinic.pdf"],
        suggested_classification: "For Approval",
      },
      token_usage: {
        prompt_tokens: 200,
        output_tokens: 100,
        total_tokens: 300,
        thoughts_tokens: 0,
        cached_tokens: 0,
        latency_ms: 420,
      },
      step_count: 2,
      created_at: "2026-11-19T00:00:00Z",
      updated_at: "2026-11-19T00:00:05Z",
      completed_at: "2026-11-19T00:00:05Z",
      attached_files: [
        {
          file_id: "file-01",
          filename: "clinic.pdf",
          folder_name: "01_Input_Documents",
          extension: ".pdf",
          mime_type: "application/pdf",
          size_bytes: 2048,
          sha256: "abc",
          current_version: 1,
        },
      ],
      steps: [
        {
          id: "step-1",
          task_id: "task-05-1",
          step_order: 1,
          module_name: "assignment_intake",
          title: "Validate assignment input & attached files",
          status: "completed",
          input_payload: null,
          output_payload: null,
          notes: null,
          started_at: "2026-11-19T00:00:00Z",
          completed_at: "2026-11-19T00:00:00Z",
          created_at: "2026-11-19T00:00:00Z",
        },
        {
          id: "step-2",
          task_id: "task-05-1",
          step_order: 2,
          module_name: "orchestrator_v0",
          title: "Orchestrator v0: understand assignment & structure plan",
          status: "completed",
          input_payload: null,
          output_payload: null,
          notes: "Done",
          started_at: "2026-11-19T00:00:00Z",
          completed_at: "2026-11-19T00:00:05Z",
          created_at: "2026-11-19T00:00:00Z",
        },
      ],
      logs: [
        {
          id: "log-1",
          action: "task.completed",
          entity_type: "task",
          actor: "orchestrator_v0",
          details_json: { model: "gemini-3.8-flash" },
          created_at: "2026-11-19T00:00:05Z",
        },
      ],
    };

    const failedSummary: TaskSummaryOut = {
      ...selectedTask,
      id: "task-05-2",
      title: "مهمة فاشلة لاختبار السجل",
      status: "failed",
      error_message: "No Gemini API key is saved in Windows Credential Manager.",
      structured_output: null,
      token_usage: {
        prompt_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
        thoughts_tokens: 0,
        cached_tokens: 0,
        latency_ms: 0,
      },
    };

    const shellHtml = renderToStaticMarkup(<App initialLang="ar" initialTab="assignments" />);
    expect(shellHtml).toContain('dir="rtl"');
    expect(shellHtml).toContain("المهام والتكليفات");
    expect(shellHtml).toContain("تكليف هندسي جديد (Orchestrator v0)");
    expect(shellHtml).toContain("سجل المهام والتكليفات (Task History)");

    const viewHtml = renderToStaticMarkup(
      <AssignmentsView
        lang="ar"
        initialProjects={sampleProjects}
        initialTasks={[selectedTask, failedSummary]}
        initialSelectedTask={selectedTask}
      />
    );
    expect(viewHtml).toContain("CLN-05");
    expect(viewHtml).toContain("مراجعة المخطط المعماري للعيادة وتحديد الملاحظات الأولية.");
    expect(viewHtml).toContain("NFPA 101 Life Safety Code");
    expect(viewHtml).toContain("ما هي السعة التصميمية المتوقعة للمرضى؟");
    expect(viewHtml).toContain("orchestrator_v0");
    expect(viewHtml).toContain("300 tokens");
    expect(viewHtml).toContain("Preliminary");
    expect(viewHtml).toContain("اقتراح النموذج: For Approval");
    expect(viewHtml).toContain("مهمة فاشلة لاختبار السجل");
    expect(viewHtml).toContain("No Gemini API key is saved in Windows Credential Manager.");
  });

  it("calls task creation, history listing, and task detail endpoints cleanly", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: "t-1", status: "completed" }), { status: 201 })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ tasks: [], total: 0 }), { status: 200 })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: "t-1", steps: [], logs: [] }), { status: 200 })
      );

    vi.stubGlobal("fetch", fetchMock);

    await createTask({
      project_id: "proj-1",
      prompt: "Check slab thickness",
      attached_file_ids: ["file-1"],
      complexity: "fast",
    });
    await listTasks({ projectId: "proj-1", status: "completed" });
    await getTaskDetail("t-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/tasks",
      expect.objectContaining({ method: "POST" })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/tasks?project_id=proj-1&status=completed",
      undefined
    );
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/tasks/t-1", undefined);
  });
});

describe("Step 06 ProjectFilesPanel Extraction UI & API client", () => {
  it("renders Arabic RTL extraction status, normalized items, formula values, and SHA-256 verification", () => {
    const sampleFiles: ProjectFileOut[] = [
      {
        id: "f-pdf-1",
        project_id: "proj-6",
        folder_name: "01_Input_Documents",
        original_filename: "boq_beam.xlsx",
        stored_relative_path: "01_Input_Documents/boq_beam.xlsx",
        mime_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        extension: ".xlsx",
        size_bytes: 4096,
        sha256: "a".repeat(64),
        is_original: true,
        status: "registered",
        classification: "Preliminary",
        current_version: 1,
        created_at: "2026-11-19T00:00:00Z",
        updated_at: "2026-11-19T00:00:00Z",
        versions: [
          {
            id: "v-1",
            file_id: "f-pdf-1",
            version_number: 1,
            stored_relative_path: "01_Input_Documents/boq_beam.xlsx",
            size_bytes: 4096,
            sha256: "a".repeat(64),
            change_note: "Initial upload",
            created_by: "owner",
            created_at: "2026-11-19T00:00:00Z",
          },
        ],
      },
    ];

    const capabilities: ExtractionCapabilitiesOut = {
      ocr: {
        installed: false,
        status: "not installed - pending owner",
        version: null,
        languages: [],
        ara_installed: false,
        eng_installed: false,
        install_url: "https://github.com/UB-Mannheim/tesseract/wiki",
        message: "Tesseract OCR (ara+eng) is not installed - pending owner.",
      },
      supported_extensions: [".pdf", ".docx", ".xlsx", ".csv", ".pptx", ".png"],
      cad_bim_deferred_extensions: [".dxf", ".dwg", ".ifc"],
      classification: "Preliminary",
    };

    const extraction: FileExtractionDetailOut = {
      id: "ext-1",
      project_id: "proj-6",
      file_id: "f-pdf-1",
      source_file: "boq_beam.xlsx",
      folder_name: "01_Input_Documents",
      extension: ".xlsx",
      version_number: 1,
      extraction_version: 1,
      source_sha256: "a".repeat(64),
      sha256_before: "a".repeat(64),
      sha256_after: "a".repeat(64),
      original_unchanged: true,
      status: "extracted",
      ocr_status: "not_needed",
      classification: "Preliminary",
      counts: {
        pages: 0,
        sheets: 1,
        slides: 0,
        tables: 1,
        formulas: 1,
        text_items: 0,
        ocr_items: 0,
        rendered_page_images: 0,
        total_items: 2,
      },
      warnings: [],
      rendered_page_images: [],
      artifact_relative_path: "03_Analysis/extractions/f-pdf-1/v1/r1/extraction.json",
      error_message: null,
      created_at: "2026-11-19T00:00:00Z",
      ocr: capabilities.ocr,
      items: [
        {
          item_index: 1,
          item_type: "cell_formula",
          source_file: "boq_beam.xlsx",
          file_id: "f-pdf-1",
          version_number: 1,
          page_or_sheet: "sheet:BOQ",
          location: "cell:D2",
          text: "3125",
          raw_values: null,
          formula: "=B2*C2",
          cached_value: "3125",
          unit_or_format: '0.00" m3"',
          extraction_method: "native",
        },
      ],
    };

    const html = renderToStaticMarkup(
      <ProjectFilesPanel
        lang="ar"
        projectId="proj-6"
        initialFiles={sampleFiles}
        initialCapabilities={capabilities}
        initialExtraction={extraction}
      />
    );

    expect(html).toContain("not installed - pending owner");
    expect(html).toContain("استخراج البيانات");
    expect(html).toContain("SHA-256 مطابق تماماً");
    expect(html).toContain("sheet:BOQ");
    expect(html).toContain("cell:D2");
    expect(html).toContain("=B2*C2");
    expect(html).toContain("3125");
  });

  it("calls extraction endpoints cleanly and builds page image URLs", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ocr: { status: "not installed - pending owner" } }), {
          status: 200,
        })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: "ext-1", status: "extracted" }), { status: 201 })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ file_id: "f-1", extractions: [], total: 0 }), { status: 200 })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: "ext-1", items: [] }), { status: 200 })
      );

    vi.stubGlobal("fetch", fetchMock);

    await getExtractionCapabilities();
    await extractProjectFile("f-1", { force_ocr: true });
    await listFileExtractions("f-1");
    await getExtractionDetail("ext-1");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/extraction/capabilities", undefined);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/files/f-1/extract",
      expect.objectContaining({ method: "POST" })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/files/f-1/extractions", undefined);
    expect(fetchMock).toHaveBeenNthCalledWith(4, "/api/extractions/ext-1", undefined);
    expect(getExtractionPageImageUrl("ext-1", 2)).toBe("/api/extractions/ext-1/pages/2");
  });

  it("renders blank/failed page reconciliation, unreliable native OCR status, and low-confidence badges", () => {
    const extraction: FileExtractionDetailOut = {
      id: "ext-recon-1",
      project_id: "proj-6",
      file_id: "f-pdf-12",
      source_file: "arabic_scan_12p.pdf",
      folder_name: "01_Input_Documents",
      extension: ".pdf",
      version_number: 1,
      extraction_version: 1,
      source_sha256: "b".repeat(64),
      sha256_before: "b".repeat(64),
      sha256_after: "b".repeat(64),
      original_unchanged: true,
      status: "extracted",
      ocr_status: "ocr_applied (native text unreliable)",
      ocr_dpi: 300,
      classification: "Preliminary",
      counts: {
        pages: 12,
        sheets: 0,
        slides: 0,
        tables: 0,
        formulas: 0,
        text_items: 0,
        ocr_items: 10,
        rendered_page_images: 12,
        total_items: 12,
      },
      page_reconciliation: {
        total_pages: 12,
        page_items_count: 12,
        reconciled: true,
        status_counts: { text: 0, ocr_text: 10, ocr_empty_or_blank: 1, failed: 1 },
        blank_pages: [11],
        failed_pages: [12],
        unreliable_native_pages: [1],
        low_confidence_pages: [3],
        low_confidence_threshold: 65,
      },
      warnings: ["Low OCR confidence on page:3: mean=41.5% (< 65%)."],
      rendered_page_images: [],
      artifact_relative_path: "03_Analysis/extractions/f-pdf-12/v1/r1/extraction.json",
      error_message: null,
      created_at: "2026-11-20T21:00:00Z",
      ocr: {
        installed: true,
        status: "installed",
        version: "tesseract 5.5.3",
        languages: ["ara", "eng"],
        ara_installed: true,
        eng_installed: true,
        install_url: "https://github.com/UB-Mannheim/tesseract/wiki",
        message: "ready",
      },
      items: [
        {
          item_index: 1,
          item_type: "ocr_text",
          source_file: "arabic_scan_12p.pdf",
          file_id: "f-pdf-12",
          version_number: 1,
          page_or_sheet: "page:3",
          location: "ocr_full_page",
          text: "نص ممسوح منخفض الدقة",
          raw_values: null,
          formula: null,
          cached_value: null,
          unit_or_format: null,
          ocr_dpi: 300,
          ocr_confidence_mean: 41.5,
          ocr_low_confidence: true,
          native_text_unreliable: true,
          page_status: "ocr_text",
          extraction_method: "ocr",
        },
        {
          item_index: 2,
          item_type: "ocr_text",
          source_file: "arabic_scan_12p.pdf",
          file_id: "f-pdf-12",
          version_number: 1,
          page_or_sheet: "page:11",
          location: "ocr_full_page",
          text: null,
          raw_values: null,
          formula: null,
          cached_value: null,
          unit_or_format: null,
          page_status: "ocr_empty_or_blank",
          extraction_method: "ocr",
        },
        {
          item_index: 3,
          item_type: "ocr_text",
          source_file: "arabic_scan_12p.pdf",
          file_id: "f-pdf-12",
          version_number: 1,
          page_or_sheet: "page:12",
          location: "ocr_full_page",
          text: null,
          raw_values: null,
          formula: null,
          cached_value: null,
          unit_or_format: null,
          page_status: "failed",
          page_error: "Simulated timeout on page 12",
          extraction_method: "ocr",
        },
      ],
    };

    const html = renderToStaticMarkup(
      <ProjectFilesPanel
        lang="en"
        projectId="proj-6"
        initialFiles={[]}
        initialExtraction={extraction}
      />
    );

    expect(html).toContain("ocr_applied (native text unreliable)");
    expect(html).toContain("12 / 12 pages");
    expect(html).toContain("page:11");
    expect(html).toContain("page:12");
    expect(html).toContain("page:3");
    expect(html).toContain("41.5%");
    expect(html).toContain("Low confidence");
    expect(html).toContain("native_text_unreliable");
    expect(html).toContain("ocr_empty_or_blank");
    expect(html).toContain("Simulated timeout on page 12");
  });
});

describe("Step 07 CAD/BIM inventory, ODA status, and Vision Summary disclaimer UI", () => {
  it("renders ODA converter status, format support matrix, CAD inventory tables, and vision non-measurement disclaimer", () => {
    const capabilities: ExtractionCapabilitiesOut = {
      ocr: {
        installed: true,
        status: "installed",
        version: "tesseract 5.5.3",
        languages: ["ara", "eng"],
        ara_installed: true,
        eng_installed: true,
        install_url: "https://github.com/UB-Mannheim/tesseract/wiki",
        message: "OCR ready",
      },
      oda: {
        installed: false,
        status: "not installed - pending owner",
        version: null,
        install_url: "https://www.opendesign.com/guestfiles/oda_file_converter",
        message: "ODA File Converter is not installed - pending owner.",
      },
      format_support_matrix: [
        {
          extension: ".dxf",
          category: "CAD Drawing",
          support_level: "native",
          provider_or_tool: "ezdxf",
          notes: "Native DXF extraction",
        },
        {
          extension: ".dwg",
          category: "CAD Binary",
          support_level: "converted_via_oda",
          provider_or_tool: "ODA -> DXF",
          notes: "Requires ODA File Converter",
        },
      ],
      supported_extensions: [".dxf", ".dwg", ".ifc", ".pdf"],
      cad_bim_deferred_extensions: [".rvt"],
      classification: "Preliminary",
    };

    const cadExtraction: FileExtractionDetailOut = {
      id: "ext-dxf-1",
      project_id: "proj-7",
      file_id: "f-dxf-1",
      source_file: "clinic_plan.dxf",
      folder_name: "02_Original_Drawings",
      extension: ".dxf",
      version_number: 1,
      extraction_version: 1,
      source_sha256: "b".repeat(64),
      sha256_before: "b".repeat(64),
      sha256_after: "b".repeat(64),
      original_unchanged: true,
      status: "extracted",
      ocr_status: "not_needed",
      cad_units: "m ($INSUNITS=6)",
      drawing_inventory: {
        kind: "cad_dxf",
        layers: [
          {
            name: "جدران-معمارية",
            color: 3,
            linetype: "Continuous",
            modelspace_entities: 4,
            paperspace_entities: 0,
            total_entities: 4,
          },
        ],
        blocks: [
          { name: "DOOR_باب_D1", insert_count: 2, definition_entities: 1, is_xref: false },
        ],
        closed_areas: [
          {
            handle: "1A0",
            layer: "جدران-معمارية",
            type: "LWPOLYLINE",
            area_native: 24.0,
            area_native_unit: "m2",
            area_m2: 24.0,
            perimeter_native: 20.0,
          },
        ],
      },
      vision_summaries: [
        {
          extraction_id: "ext-dxf-1",
          page_number: 1,
          ai_interpretation_only: true,
          disclaimer: "AI visual interpretation only — NOT a verified engineering measurement.",
          provider_name: "gemini",
          model_name: "gemini-3.8-flash",
          drawing_title: "Clinic Plan Sheet A-101",
          discipline_guess: "Architectural",
          visible_labels_and_notes: ["Operating Room"],
          key_elements_observed: ["Closed room perimeter"],
          uncertainty_notes: ["Scale bar not checked visually"],
          token_usage: { prompt_tokens: 100, output_tokens: 40, total_tokens: 140 },
          artifact_relative_path: "03_Analysis/extractions/f-dxf-1/v1/r1/vision_page_001_s1.json",
          classification: "Preliminary",
        },
      ],
      classification: "Preliminary",
      counts: {
        pages: 0,
        sheets: 0,
        slides: 0,
        tables: 0,
        formulas: 0,
        text_items: 1,
        ocr_items: 0,
        rendered_page_images: 1,
        layers: 1,
        blocks: 1,
        block_inserts: 2,
        entities: 6,
        dimensions: 1,
        polylines: 1,
        closed_areas: 1,
        total_items: 4,
      },
      warnings: [],
      rendered_page_images: ["03_Analysis/extractions/f-dxf-1/v1/r1/pages/page_001.png"],
      artifact_relative_path: "03_Analysis/extractions/f-dxf-1/v1/r1/extraction.json",
      error_message: null,
      created_at: "2026-11-19T00:00:00Z",
      ocr: capabilities.ocr,
      oda: capabilities.oda,
      items: [],
    };

    const html = renderToStaticMarkup(
      <ProjectFilesPanel
        lang="en"
        projectId="proj-7"
        initialFiles={[]}
        initialCapabilities={capabilities}
        initialExtraction={cadExtraction}
      />
    );

    expect(html).toContain("ODA File Converter Status");
    expect(html).toContain("not installed - pending owner");
    expect(html).toContain("Format Support Matrix");
    expect(html).toContain("converted_via_oda");
    expect(html).toContain("جدران-معمارية");
    expect(html).toContain("DOOR_باب_D1");
    expect(html).toContain("24 m2");
    expect(html).toContain("AI INTERPRETATION ONLY — NOT MEASUREMENT");
    expect(html).toContain("Clinic Plan Sheet A-101");
  });

  it("posts vision summary requests cleanly via API client", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(
        JSON.stringify({ extraction_id: "ext-1", page_number: 1, ai_interpretation_only: true }),
        { status: 201 }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    const out = await summarizeDrawingVision("ext-1", { page_number: 1, complexity: "fast" });
    expect(out.ai_interpretation_only).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/extractions/ext-1/vision-summary",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("renders doubtful-units warning, owner confirm control, raw CP1256 block names, and calls confirm-unit endpoint", async () => {
    const capabilities: ExtractionCapabilitiesOut = {
      ocr: {
        installed: true,
        status: "installed",
        version: "5.5.3",
        languages: ["ara", "eng"],
        ara_installed: true,
        eng_installed: true,
        install_url: "https://github.com/UB-Mannheim/tesseract/wiki",
        message: "installed",
      },
      oda: {
        installed: true,
        status: "installed",
        version: "27.10.0",
        install_url: "https://www.opendesign.com/guestfiles/oda_file_converter",
        message: "installed",
      },
      format_support_matrix: [],
      supported_extensions: [".dxf", ".dwg"],
      cad_bim_deferred_extensions: [".rvt"],
      classification: "Preliminary",
    };

    const doubtfulExtraction: FileExtractionDetailOut = {
      id: "ext-doubt-1",
      project_id: "proj-7b",
      file_id: "f-dxf-7b",
      source_file: "synthetic_doubtful.dxf",
      folder_name: "02_Original_Drawings",
      extension: ".dxf",
      version_number: 1,
      extraction_version: 1,
      source_sha256: "deadbeef1234567890",
      sha256_before: "deadbeef1234567890",
      sha256_after: "deadbeef1234567890",
      original_unchanged: true,
      status: "extracted",
      ocr_status: "not_applicable",
      cad_units: "in ($INSUNITS=1; DOUBTFUL)",
      units_doubtful: true,
      units_status: "doubtful",
      owner_confirmed_unit: null,
      drawing_inventory: {
        kind: "cad_dxf",
        layers: [{ name: "0", color: 7, linetype: "Continuous", modelspace_entities: 2, paperspace_entities: 0, total_entities: 2 }],
        blocks: [
          {
            name: "شجرة ملونة",
            raw_name: "ÔÌÑÉ ãáæäÉ",
            insert_count: 1,
            definition_entities: 3,
            is_xref: false,
          },
        ],
        closed_areas: [
          {
            handle: "2B0",
            layer: "0",
            type: "LWPOLYLINE",
            area_native: 7032.67,
            area_native_unit: "sq_in",
            area_m2: null,
            perimeter_native: 412.5,
          },
        ],
      },
      vision_summaries: [],
      classification: "Preliminary",
      counts: {
        pages: 0,
        sheets: 0,
        slides: 0,
        tables: 0,
        formulas: 0,
        text_items: 0,
        ocr_items: 0,
        rendered_page_images: 0,
        layers: 1,
        blocks: 1,
        block_inserts: 1,
        entities: 5,
        dimensions: 3,
        polylines: 1,
        closed_areas: 1,
        total_items: 6,
      },
      warnings: ["units doubtful - owner must confirm drawing unit"],
      rendered_page_images: [],
      artifact_relative_path: "03_Analysis/extractions/f-dxf-7b/v1/r1/extraction.json",
      error_message: null,
      created_at: "2026-11-20T00:00:00Z",
      ocr: capabilities.ocr,
      oda: capabilities.oda,
      items: [],
    };

    const html = renderToStaticMarkup(
      <ProjectFilesPanel
        lang="en"
        projectId="proj-7b"
        initialFiles={[]}
        initialCapabilities={capabilities}
        initialExtraction={doubtfulExtraction}
      />
    );

    expect(html).toContain("units doubtful - owner must confirm drawing unit");
    expect(html).toContain("Confirm Unit");
    expect(html).toContain("7032.67 sq_in");
    expect(html).toContain("شجرة ملونة");
    expect(html).toContain("ÔÌÑÉ ãáæäÉ");

    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify({ ...doubtfulExtraction, owner_confirmed_unit: "m", units_doubtful: false }), {
        status: 200,
      })
    );
    vi.stubGlobal("fetch", fetchMock);
    const updated = await confirmExtractionDrawingUnit("ext-doubt-1", "m");
    expect(updated.owner_confirmed_unit).toBe("m");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/extractions/ext-doubt-1/confirm-unit",
      expect.objectContaining({ method: "POST" })
    );

    const confirmedHtml = renderToStaticMarkup(
      <ProjectFilesPanel
        lang="en"
        projectId="proj-7b"
        initialFiles={[]}
        initialCapabilities={capabilities}
        initialExtraction={{
          ...doubtfulExtraction,
          units_doubtful: false,
          units_status: "owner_confirmed",
          owner_confirmed_unit: "m",
          cad_units: "m (owner confirmed; file header in, $INSUNITS=1)",
          drawing_inventory: {
            ...doubtfulExtraction.drawing_inventory,
            closed_areas: [
              {
                handle: "2B0",
                layer: "0",
                type: "LWPOLYLINE",
                area_native: 2.040006,
                area_native_unit: "sq_in",
                perimeter_native: 5.8,
                perimeter_unit: "in",
                display_area: 2.040006,
                display_area_unit: "sq m",
                display_perimeter: 5.8,
                display_perimeter_unit: "m",
                raw_declared_unit: "in",
                area_m2: 2.040006,
              },
            ],
          },
        }}
      />
    );
    expect(confirmedHtml).toContain("Confirmed Display Area");
    expect(confirmedHtml).toContain("2.040006 sq m");
    expect(confirmedHtml).toContain("5.8 m");
    expect(confirmedHtml).toContain("raw: 2.040006 sq_in");
    expect(confirmedHtml).toContain("raw: 5.8 in");
  });
});

describe("App Step 08 Controlled Internet Research UI (RTL/LTR)", () => {
  it("renders Research History tab and ResearchView in Arabic RTL and English LTR with unreviewed/injection badges", async () => {
    const appAr = renderToStaticMarkup(<App initialLang="ar" initialTab="research" />);
    expect(appAr).toContain('dir="rtl"');
    expect(appAr).toContain("البحث الهندسي المضبوط");
    expect(appAr).toContain("سجل أبحاث الإنترنت والمصادر");

    const sampleSummary: ResearchRunSummaryOut = {
      id: "res-run-1",
      project_id: "p-1",
      task_id: null,
      query: "متطلبات التهوية لغرف العمليات NFPA 99",
      search_provider: "duckduckgo_lite",
      classification: "Preliminary",
      status: "partial_inaccessible",
      summary: "Verified NFPA page; ISO paywall marked unreviewed.",
      error_message: null,
      total_sources: 2,
      accessible_sources: 1,
      inaccessible_sources: 1,
      token_usage: { prompt_tokens: 150, output_tokens: 60, total_tokens: 210, thoughts_tokens: 0, cached_tokens: 0, latency_ms: 0 },
      artifact_relative_path: "11_References/research/res-run-1/research_log.json",
      created_at: "2026-11-20T18:00:00Z",
    };

    const sampleDetail: ResearchRunDetailOut = {
      ...sampleSummary,
      structured_output: {
        summary: "Verified NFPA page; ISO paywall marked unreviewed.",
        verified_findings: [
          {
            claim: "Operating theatre ventilation criteria cited directly from fetched page.",
            source_name: "NFPA 99 Overview",
            source_url: "https://nfpa.org/codes/nfpa-99",
            publication_date: "2024-01-15",
            priority_tier: "standards_bodies",
          },
        ],
        unreviewed_or_inaccessible: [
          "https://iso.org/standard/paywalled.html — UNREVIEWED (HTTP 403 Forbidden)",
        ],
        standards_and_gaps: [],
        injection_attempts_ignored: [
          "Ignored untrusted directive from https://nfpa.org/codes/nfpa-99: ignore all previous instructions",
        ],
        assumptions: ["Assumption (to confirm with owner): Verify local hospital authority addendum."],
        suggested_classification: "Preliminary",
      },
      sources: [
        {
          id: "src-1",
          research_run_id: "res-run-1",
          project_id: "p-1",
          task_id: null,
          source_name: "NFPA 99 Overview",
          url: "https://nfpa.org/codes/nfpa-99",
          publication_date: "2024-01-15",
          access_date: "2026-11-20T18:00:00Z",
          query_text: sampleSummary.query,
          extracted_info: "Medical gas and essential ventilation controls.",
          reliability_rating: "high_standards_body",
          source_type: "standard",
          source_priority_tier: "standards_bodies",
          priority_rank: 2,
          access_status: "accessible",
          reviewed: true,
          http_status: 200,
          failure_reason: null,
          untrusted_neutralized: true,
          created_at: "2026-11-20T18:00:00Z",
        },
        {
          id: "src-2",
          research_run_id: "res-run-1",
          project_id: "p-1",
          task_id: null,
          source_name: "ISO Restricted Standard",
          url: "https://iso.org/standard/paywalled.html",
          publication_date: null,
          access_date: "2026-11-20T18:00:00Z",
          query_text: sampleSummary.query,
          extracted_info: "UNREVIEWED — Document inaccessible: HTTP 403",
          reliability_rating: "unreviewed",
          source_type: "standard",
          source_priority_tier: "standards_bodies",
          priority_rank: 99,
          access_status: "inaccessible",
          reviewed: false,
          http_status: 403,
          failure_reason: "HTTP 403",
          untrusted_neutralized: true,
          created_at: "2026-11-20T18:00:00Z",
        },
        {
          id: "src-3",
          research_run_id: "res-run-1",
          project_id: "p-1",
          task_id: null,
          source_name: "Book Chapter Stub",
          url: "https://doi.org/10.5040/stub",
          publication_date: "2021-01-01",
          access_date: "2026-11-20T18:00:00Z",
          query_text: sampleSummary.query,
          extracted_info: "NOT RELEVANT — Does not match query",
          reliability_rating: "unrated",
          source_type: "crossref:book-chapter",
          source_priority_tier: "reputable",
          priority_rank: 99,
          tier_is_provider_claim: true,
          tier_claim_label: "Provider claim (crossref: book-chapter) — unverified metadata",
          access_status: "not_relevant",
          reviewed: false,
          http_status: 200,
          failure_reason: "Not relevant",
          untrusted_neutralized: true,
          created_at: "2026-11-20T18:00:00Z",
        },
      ],
    };

    const htmlEn = renderToStaticMarkup(
      <ResearchView
        lang="en"
        initialRuns={[sampleSummary]}
        initialDetail={sampleDetail}
      />
    );
    expect(htmlEn).toContain("Controlled Internet Research");
    expect(htmlEn).toContain("UNREVIEWED — Download &amp; Upload in Projects &amp; Files");
    expect(htmlEn).toContain("https://iso.org/standard/paywalled.html");
    expect(htmlEn).toContain("Untrusted Prompt-Injection Attempts Safely Ignored");
    expect(htmlEn).toContain("high_standards_body");
    expect(htmlEn).toContain("Inaccessible — Unreviewed");
    expect(htmlEn).toContain("Not Relevant — Omitted");
    expect(htmlEn).toContain("unrated");
    expect(htmlEn).toContain("Provider claim");
    expect(htmlEn).toContain("unranked");
    expect(htmlEn).not.toContain("#99");

    // Verify pre-flight token estimate confirmation banner before calling Gemini on un-synthesized run
    const preflightDetail: ResearchRunDetailOut = {
      ...sampleDetail,
      estimated_prompt_tokens: 620,
      prompt_char_count: 2170,
      prompt_char_cap: 10000,
      step04_daily_tokens_remaining: 499000,
      token_usage: { prompt_tokens: 0, output_tokens: 0, total_tokens: 0, thoughts_tokens: 0, cached_tokens: 0, latency_ms: 0 },
    };
    const preflightHtml = renderToStaticMarkup(
      <ResearchView lang="en" initialRuns={[sampleSummary]} initialDetail={preflightDetail} />
    );
    expect(preflightHtml).toContain("~620 est. prompt tokens");
    expect(preflightHtml).toContain("Confirm &amp; Run Gemini Synthesis");
    expect(preflightHtml).toContain("499,000");

    // Verify Arabic translation of providers, statuses, tiers, unrated, not_relevant, and unranked label
    const htmlAr = renderToStaticMarkup(
      <ResearchView
        lang="ar"
        initialRuns={[sampleSummary]}
        initialDetail={sampleDetail}
      />
    );
    expect(htmlAr).toContain("DuckDuckGo Lite (أفضل جهد");
    expect(htmlAr).toContain("جزئي (توجد مستندات متعذرة)");
    expect(htmlAr).toContain("هيئات المواصفات القياسية");
    expect(htmlAr).toContain("غير ذي صلة — لم يُقتبس");
    expect(htmlAr).toContain("غير مُقيَّم");
    expect(htmlAr).toContain("ادعاء من المزوّد (غير مُتحقق)");
    expect(htmlAr).toContain("غير مصنّف");
    expect(htmlAr).not.toContain("#99");

    // Step 08B UI checks: explicit Link-to-Project owner-file hint & Last modified (HTTP) relabeling
    expect(htmlEn).toContain("select a project to show owner-file picker");
    expect(htmlEn).toContain("Owner-file picker appears only after a project is selected");
    expect(htmlAr).toContain("يظهر منتقي الملفات فقط بعد اختيار المشروع");

    const httpLastModOnlyDetail: ResearchRunDetailOut = {
      ...sampleDetail,
      sources: [
        {
          id: "src-http-lm",
          research_run_id: sampleSummary.id,
          project_id: null,
          task_id: null,
          source_name: "Commercial Panel Article",
          url: "https://ecalpro.com/panel-guide",
          publication_date: "Last modified (HTTP): Wed, 18 Nov 2026 09:00:00 GMT",
          publication_date_kind: "http_last_modified",
          access_date: "2026-11-21T10:00:00Z",
          query_text: sampleSummary.query,
          extracted_info: "Summary text",
          reliability_rating: "unrated",
          source_type: "generation_artifact_downgraded",
          source_priority_tier: "unverified",
          priority_rank: 99,
          tier_is_provider_claim: true,
          tier_claim_label: "URL/domain heuristic claim - unverified (unverified)",
          access_status: "accessible",
          reviewed: true,
          http_status: 200,
          failure_reason: null,
          untrusted_neutralized: true,
          created_at: "2026-11-21T10:00:00Z",
        },
      ],
    };
    const httpLmEnHtml = renderToStaticMarkup(
      <ResearchView lang="en" initialRuns={[sampleSummary]} initialDetail={httpLastModOnlyDetail} />
    );
    expect(httpLmEnHtml).toContain("<th>Last modified (HTTP)</th>");
    expect(httpLmEnHtml).not.toContain("<th>Published</th>");
    expect(httpLmEnHtml).toContain("Last modified (HTTP): Wed, 18 Nov 2026 09:00:00 GMT");

    const httpLmArHtml = renderToStaticMarkup(
      <ResearchView lang="ar" initialRuns={[sampleSummary]} initialDetail={httpLastModOnlyDetail} />
    );
    expect(httpLmArHtml).toContain("<th>آخر تعديل (HTTP)</th>");

    // Verify Arabic translation of Step 06/07 status lines & Format Support Matrix
    const matrixAr = renderToStaticMarkup(
      <ProjectFilesPanel
        lang="ar"
        projectId="proj-ar-matrix"
        initialFiles={[]}
        initialCapabilities={{
          ocr: {
            installed: true,
            status: "installed",
            version: "5.5.3",
            languages: ["ara", "eng"],
            ara_installed: true,
            eng_installed: true,
            install_url: "https://github.com/UB-Mannheim/tesseract/wiki",
            message: "installed",
          },
          oda: {
            installed: false,
            status: "not installed - pending owner",
            version: null,
            install_url: "https://www.opendesign.com/guestfiles/oda_file_converter",
            message: "not installed",
          },
          format_support_matrix: [
            {
              extension: ".doc .xls .ppt .rtf .ods .html .json .xml .svg .landxml",
              category: "Other Accepted Formats",
              support_level: "stored_read_only",
              provider_or_tool: "Stored Read-Only (Not Extracted)",
              notes: "other accepted formats (.doc .xls .ppt .rtf .ods .html .json .xml .svg .landxml): stored as read-only original, not extracted.",
            },
          ],
          supported_extensions: [".dxf", ".pdf"],
          cad_bim_deferred_extensions: [".rvt"],
          classification: "Preliminary",
        }}
      />
    );
    expect(matrixAr).toContain("مثبّت وجاهز");
    expect(matrixAr).toContain("غير مثبّت — بانتظار المالك");
    expect(matrixAr).toContain("محفوظ للقراءة فقط (دون استخراج)");
    expect(matrixAr).toContain("تُحفظ كأصل للقراءة فقط ولا يُستخرج محتواها");

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(sampleDetail), { status: 201 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ runs: [sampleSummary], total: 1, classification: "Preliminary" }), {
          status: 200,
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    const created = await runControlledResearch({ query: "NFPA 99", classification: "Preliminary" });
    expect(created.id).toBe("res-run-1");
    const listOut = await listResearchRuns();
    expect(listOut.total).toBe(1);
  });
});

describe("App Step 09 Review Reports & Deliverables UI (RTL/LTR)", () => {
  it("renders Deliverables & Reports tab, source-linked findings, separated categories, token estimate, and downloads", async () => {
    const appAr = renderToStaticMarkup(<App initialLang="ar" initialTab="deliverables" />);
    expect(appAr).toContain('dir="rtl"');
    expect(appAr).toContain("التقارير والمخرجات");
    expect(appAr).toContain("إصدار تقرير المراجعة الهندسية");

    const sampleDeliverables: DeliverableOut[] = [
      {
        id: "del-08-pdf",
        project_id: "proj-09",
        report_id: "rep-09",
        task_id: null,
        file_id: null,
        title: "Clinic Review Report (Rev 01 — 08_Reports)",
        deliverable_type: "review_report_working",
        discipline: "Multidisciplinary",
        format: "pdf",
        classification: "For Review",
        status: "issued",
        version: 1,
        folder_name: "08_Reports",
        filename: "review_rep09_v1.pdf",
        relative_path: "08_Reports/review_rep09_v1.pdf",
        mime_type: "application/pdf",
        size_bytes: 18420,
        sha256: "abcdef1234567890",
        summary: "Summary",
        download_url: "/api/deliverables/del-08-pdf/download",
        created_at: "2026-11-20T20:00:00Z",
        updated_at: "2026-11-20T20:00:00Z",
      },
      {
        id: "del-10-docx",
        project_id: "proj-09",
        report_id: "rep-09",
        task_id: null,
        file_id: null,
        title: "Clinic Review Report (Rev 01 — 10_Final_Deliverables)",
        deliverable_type: "review_report",
        discipline: "Multidisciplinary",
        format: "docx",
        classification: "For Review",
        status: "issued",
        version: 1,
        folder_name: "10_Final_Deliverables",
        filename: "clinic_review_v1_For_Review.docx",
        relative_path: "10_Final_Deliverables/clinic_review_v1_For_Review.docx",
        mime_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes: 22150,
        sha256: "123456abcdef7890",
        summary: "Summary",
        download_url: "/api/deliverables/del-10-docx/download",
        created_at: "2026-11-20T20:00:00Z",
        updated_at: "2026-11-20T20:00:00Z",
      },
    ];

    const srcRef = {
      ref_id: "EXT-1",
      source_kind: "extraction",
      source_id: "ext-09",
      file_id: "file-09",
      extraction_id: "ext-09",
      research_run_id: null,
      url: null,
      source_name: "plan_metric.dxf",
      page_or_sheet: "ModelSpace",
      location: "$INSUNITS=6 (m)",
      excerpt: "Closed room 24.0 m2",
    };

    const sampleReport: ReviewReportDetailOut = {
      id: "rep-09",
      project_id: "proj-09",
      project_code: "CLN-09",
      project_name: "عيادة طرابلس",
      task_id: null,
      title: "تقرير مراجعة العيادة",
      discipline: "Multidisciplinary",
      language: "ar",
      classification: "For Review",
      revision: "Rev 01",
      version: 1,
      status: "generated",
      is_inventory_only: true,
      summary: "تقرير جرد وفحص استخراج حتمي (ليس مراجعة هندسية فنية).",
      findings_count: 1,
      estimated_prompt_tokens: 310,
      prompt_char_count: 1085,
      prompt_char_cap: 10000,
      step04_daily_tokens_remaining: 498000,
      step04_monthly_tokens_remaining: 4998000,
      token_usage: { prompt_tokens: 0, output_tokens: 0, total_tokens: 0, thoughts_tokens: 0, cached_tokens: 0, latency_ms: 0 },
      error_message: null,
      created_at: "2026-11-20T20:00:00Z",
      updated_at: "2026-11-20T20:00:00Z",
      revision_block: {
        version: 1,
        revision: "Rev 01",
        classification: "For Review",
        prepared_by: "Engineering Agent (Deterministic Inventory & Check — 0 AI tokens)",
        review_notice: "Requires licensed engineer sign-off",
        issued_at_iso: "2026-11-20T20:00:00Z",
        change_note: "Initial issue",
        source_files_count: 2,
        reviewed_research_count: 1,
      },
      document_register: [
        {
          file_name: "plan_metric.dxf",
          file_type: "DXF",
          pages_or_entities: "120 entities / 5 layers",
          extraction_status: "extracted (m)",
          confidence: "Deterministic CAD geometry",
        },
      ],
      findings: [
        {
          finding_id: "REV-001",
          discipline: "CAD Coordination",
          severity: "high",
          location_or_drawing_ref: "plan_metric.dxf — ModelSpace",
          evidence: "Closed polyline room verified at 24.0 m2.",
          recommendation: "Confirm partition wall finish thickness.",
          status: "needs_verification",
          statement_category: "verified_fact",
          source_links: [srcRef],
        },
      ],
      verified_facts: [{ category: "verified_fact", text: "Deterministic CAD layers=5, entities=120.", source_links: [srcRef] }],
      verified_facts_total: 18,
      verified_facts_shown: 1,
      appendix_verified_facts: [{ category: "verified_fact", text: "Deterministic CAD layers=5, entities=120.", source_links: [srcRef] }],
      ocr_text_items: [
        {
          file_id: "file-ocr-1",
          source_file: "scanned_sheet.pdf",
          page_or_sheet: "page:1",
          confidence_mean: 76.5,
          low_confidence: false,
          native_text_unreliable: true,
          status_label: "OCR (confidence 76.5%, not verified)",
          text: "Scanned beam schedule text snippet",
          source_links: [srcRef],
        },
      ],
      ocr_text_items_total: 1,
      calculated_items: [
        {
          category: "calculated",
          text: "Layer A-AREA: 24.0 m2 (geometric sum, not net building area)",
          formula_or_method: "Python deterministic layer sum",
          source_links: [srcRef],
        },
      ],
      assumptions: [
        {
          category: "assumption",
          text: "افتراض أولي يحتاج تأكيد المالك: سماكة اللياسة غير محددة.",
          source_links: [],
        },
      ],
      recommendations: [{ category: "recommendation", text: "Confirm partition wall finish thickness.", source_links: [srcRef] }],
      gaps_or_unextracted: ["External 403 source excluded."],
      source_registry: [srcRef],
      deliverables: sampleDeliverables,
    };

    const htmlAr = renderToStaticMarkup(
      <DeliverablesView
        lang="ar"
        initialDeliverables={sampleDeliverables}
        initialReport={sampleReport}
      />
    );
    expect(htmlAr).toContain("For Review");
    expect(htmlAr).toContain("Rev 01");
    expect(htmlAr).toContain("REV-001");
    expect(htmlAr).toContain("EXT-1");
    expect(htmlAr).toContain("plan_metric.dxf");
    expect(htmlAr).toContain("~310 est. prompt tokens");
    expect(htmlAr).toContain("سجل المستندات والملفات");
    expect(htmlAr).toContain("حقائق حتمية وبيانات أصلية (Verified Facts)");
    expect(htmlAr).toContain("قيم محسوبة برمجياً (مجاميع هندسية وليست صافي مساحة مبنى)");
    expect(htmlAr).toContain("نصوص مستخرجة بالتعرف الضوئي (OCR — غير مُتحقَّق منها)");
    expect(htmlAr).toContain("Showing 1 of 18");
    expect(htmlAr).toContain("Scanned beam schedule text snippet");
    expect(htmlAr).toContain("افتراضات أولية (تحتاج تأكيد المالك)");
    expect(htmlAr).toContain("/api/deliverables/del-08-pdf/download");
    expect(htmlAr).toContain("/api/deliverables/del-10-docx/download");

    const htmlEn = renderToStaticMarkup(
      <DeliverablesView
        lang="en"
        initialDeliverables={sampleDeliverables}
        initialReport={sampleReport}
      />
    );
    expect(htmlEn).toContain("Generate Engineering Review Report");
    expect(htmlEn).toContain("Document Register");
    expect(htmlEn).toContain("NOT an engineering review");
    expect(htmlEn).toContain("Verified Facts (Deterministic / Native Only)");
    expect(htmlEn).toContain("Extracted Text (OCR — Not Verified)");
    expect(htmlEn).toContain("Calculated Quantities (Geometric Sums — Not Net Building Area)");
    expect(htmlEn).toContain("Showing 1 of 18");
    expect(htmlEn).toContain("10_Final_Deliverables");
    expect(getDeliverableDownloadUrl("del-10-docx")).toBe("/api/deliverables/del-10-docx/download");

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(sampleReport), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ deliverables: sampleDeliverables, total: 2, classification: "Preliminary" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(sampleReport), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const createdRep = await generateReviewReport("proj-09", { language: "ar", classification: "For Review" });
    expect(createdRep.revision).toBe("Rev 01");
    const delivs = await listDeliverables({ project_id: "proj-09" });
    expect(delivs.total).toBe(2);
    const enhanced = await enhanceReviewReportAi("rep-09", "fast");
    expect(enhanced.id).toBe("rep-09");
  });
});

describe("App Step 10 BOQ & quantity UI", () => {
  it("renders Arabic RTL & English LTR BOQ tables, verification badges, LYD currency, checks, flagged items, 06_BOQ exports, and API calls", async () => {
    const sampleDelivs: DeliverableOut[] = [
      {
        id: "del-boq-xlsx",
        project_id: "proj-10",
        boq_id: "boq-10",
        title: "BOQ Schedule (v1 XLSX — LYD)",
        deliverable_type: "boq_schedule",
        discipline: "quantity_surveying",
        format: "xlsx",
        classification: "Preliminary",
        status: "issued",
        version: 1,
        folder_name: "06_BOQ",
        filename: "boq_clinic_v1.xlsx",
        relative_path: "06_BOQ/boq_clinic_v1.xlsx",
        mime_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes: 7200,
        sha256: "b".repeat(64),
        download_url: "/api/deliverables/del-boq-xlsx/download",
        created_at: "2026-11-21T10:00:00Z",
        updated_at: "2026-11-21T10:00:00Z",
      },
      {
        id: "del-boq-csv",
        project_id: "proj-10",
        boq_id: "boq-10",
        title: "BOQ Schedule (v1 CSV — LYD)",
        deliverable_type: "boq_schedule",
        discipline: "quantity_surveying",
        format: "csv",
        classification: "Preliminary",
        status: "issued",
        version: 1,
        folder_name: "06_BOQ",
        filename: "boq_clinic_v1.csv",
        relative_path: "06_BOQ/boq_clinic_v1.csv",
        mime_type: "text/csv",
        size_bytes: 1200,
        sha256: "c".repeat(64),
        download_url: "/api/deliverables/del-boq-csv/download",
        created_at: "2026-11-21T10:00:00Z",
        updated_at: "2026-11-21T10:00:00Z",
      },
    ];

    const sampleBoq: BoqDetailOut = {
      id: "boq-10",
      project_id: "proj-10",
      project_code: "BOQ-10",
      project_name: "Clinic BOQ",
      title: "مقايسة العيادة — Rev 01",
      language: "ar",
      currency: "LYD",
      classification: "For Review",
      revision: "Rev 01",
      version: 1,
      export_version: 1,
      source_scope: "extracted",
      status: "exported",
      items_count: 3,
      grand_total: 3600,
      issues_count: 1,
      high_issues_count: 1,
      created_at: "2026-11-21T10:00:00Z",
      updated_at: "2026-11-21T10:00:00Z",
      checks: {
        total_items: 3,
        verified_items_count: 1,
        needs_check_items_count: 1,
        manual_items_count: 1,
        priced_items_count: 1,
        unpriced_items_count: 2,
        verified_priced_subtotal: 3600,
        needs_check_priced_subtotal: 0,
        grand_total: 3600,
        issues_count: 1,
        high_issues_count: 1,
        issues: [
          {
            issue_id: "CHK-001",
            check_type: "unverified_unit",
            severity: "high",
            item_id: "item-2",
            item_no: "CAD-A-02",
            message: "Unconfirmed unit on CAD-A-02 requires /confirm-unit.",
            recommended_action: "Confirm drawing unit before pricing.",
          },
        ],
        flagged_item_ids: ["item-2"],
        flagged_items: [
          {
            item_id: "item-2",
            item_no: "CAD-A-02",
            description: "Unconfirmed CAD contour area",
            unit: "unconfirmed (in sq)",
            quantity: 60,
            verification_status: "Extracted-Needs-Check",
            reason: "Tagged Extracted-Needs-Check — human review required",
          },
        ],
      },
      items: [
        {
          id: "item-1",
          boq_sheet_id: "boq-10",
          row_order: 1,
          item_no: "CAD-A-01",
          description: "Geometric area — layer A-AREA",
          unit: "m2",
          quantity: 24,
          unit_rate: 150,
          total: 3600,
          technical_reference: "DXF deterministic area sum",
          drawing_reference: "plan.dxf | layer:A-AREA | LWPOLYLINE",
          remarks: "Verified owner unit",
          verification_status: "Extracted-Verified",
          rate_source_kind: "owner_input",
          rate_source_ref: "Owner schedule 2026-11-20",
          rate_source_date: "2026-11-20",
          created_at: "2026-11-21T10:00:00Z",
          updated_at: "2026-11-21T10:00:00Z",
        },
        {
          id: "item-2",
          boq_sheet_id: "boq-10",
          row_order: 2,
          item_no: "CAD-A-02",
          description: "Unconfirmed CAD contour area",
          unit: "unconfirmed (in sq)",
          quantity: 60,
          unit_rate: null,
          total: null,
          drawing_reference: "doubtful.dxf | layer:A-AREA",
          remarks: "BLOCKED METRIC CONVERSION",
          verification_status: "Extracted-Needs-Check",
          created_at: "2026-11-21T10:00:00Z",
          updated_at: "2026-11-21T10:00:00Z",
        },
        {
          id: "item-3",
          boq_sheet_id: "boq-10",
          row_order: 3,
          item_no: "MAN-01",
          description: "Emergency lighting fixture",
          unit: "nos",
          quantity: 8,
          unit_rate: null,
          total: null,
          verification_status: "Manual",
          created_at: "2026-11-21T10:00:00Z",
          updated_at: "2026-11-21T10:00:00Z",
        },
      ],
      deliverables: sampleDelivs,
      source_metadata: {},
    };

    const htmlAr = renderToStaticMarkup(<BoqView lang="ar" initialBoq={sampleBoq} />);
    expect(htmlAr).toContain("مقايسة العيادة");
    expect(htmlAr).toContain("LYD");
    expect(htmlAr).toContain("Extracted-Verified");
    expect(htmlAr).toContain("Extracted-Needs-Check");
    expect(htmlAr).toContain("Manual");
    expect(htmlAr).toContain("CHK-001");
    expect(htmlAr).toContain("06_BOQ/boq_clinic_v1.xlsx");
    expect(htmlAr).toContain("/api/deliverables/del-boq-xlsx/download");

    const htmlEn = renderToStaticMarkup(<BoqView lang="en" initialBoq={sampleBoq} />);
    expect(htmlEn).toContain("Build BOQ (DXF / IFC / XLSX / PDF)");
    expect(htmlEn).toContain("Items Flagged for Human Verification");
    expect(htmlEn).toContain("Export XLSX (Live Formulas) + CSV to 06_BOQ");
    expect(htmlEn).toContain("Unsourced or undated research unit rates and unconfirmed CAD-unit pricing are blocked.");

    const appBoqHtml = renderToStaticMarkup(<App initialLang="ar" initialTab="boq" />);
    expect(appBoqHtml).toContain("جداول الكميات (BOQ)");
    expect(appBoqHtml).toContain("LYD");

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(sampleBoq), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ sheets: [sampleBoq], total: 1, classification: "For Review" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(sampleBoq), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(sampleBoq), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(sampleBoq), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(sampleBoq), { status: 200 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            boq: sampleBoq,
            xlsx_deliverable: sampleDelivs[0],
            csv_deliverable: sampleDelivs[1],
          }),
          { status: 201 }
        )
      );
    vi.stubGlobal("fetch", fetchMock);

    const createdBoq = await createBoqSheet("proj-10", { currency: "LYD", language: "ar" });
    expect(createdBoq.currency).toBe("LYD");
    const listed = await listProjectBoqSheets("proj-10");
    expect(listed.total).toBe(1);
    const updatedCurr = await updateBoqSheet("boq-10", { currency: "USD" });
    expect(updatedCurr.id).toBe("boq-10");
    const added = await addBoqItem("boq-10", {
      item_no: "M-02",
      description: "Test manual line",
      unit: "nos",
      quantity: 2,
    });
    expect(added.id).toBe("boq-10");
    const priced = await updateBoqItem("boq-10", "item-3", {
      unit_rate: 75,
      rate_source_kind: "owner_input",
      rate_source_ref: "Owner input",
    });
    expect(priced.id).toBe("boq-10");
    const checked = await rerunBoqChecks("boq-10");
    expect(checked.checks.issues_count).toBe(1);
    const exported = await exportBoqDeliverables("boq-10", { language: "en" });
    expect(exported.xlsx_deliverable.folder_name).toBe("06_BOQ");
  });
});
