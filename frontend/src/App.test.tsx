import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { App } from "./App";
import {
  createProject,
  deleteProviderApiKey,
  getFileDownloadUrl,
  getProject,
  getProviderSettings,
  getSupportedExtensions,
  listProjectFiles,
  listProjects,
  saveProviderApiKey,
  testProviderConnection,
  updateProviderSettings,
  uploadProjectFiles,
} from "./api";
import { ProjectFilesPanel } from "./components/ProjectFilesPanel";
import { ProjectWorkspaceView } from "./components/ProjectWorkspaceView";
import { ProviderSettingsView } from "./components/ProviderSettingsView";
import type { ProjectDetail, ProjectFileOut, ProjectSummary, ProviderSettingsOut } from "./types";

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
            { id: "gemini-2.5-flash", label: "Gemini 2.5 Flash", tier: "fast" },
            { id: "gemini-2.5-pro", label: "Gemini 2.5 Pro", tier: "deep" },
          ],
        },
      ],
      models: { fast: "gemini-2.5-flash", deep: "gemini-2.5-pro" },
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
        model: "gemini-2.5-flash",
        message: "Connected cleanly to gemini-2.5-flash.",
        latency_ms: 95,
      },
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
    expect(settingsHtml).toContain("gemini-2.5-flash");
    expect(settingsHtml).toContain("gemini-2.5-pro");
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
        new Response(JSON.stringify({ connected: true, model: "gemini-2.5-flash" }), {
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
      models: { fast: "gemini-2.5-flash", deep: "gemini-2.5-pro" },
      usage_limits: {
        daily_request_limit: 100,
        daily_token_limit: 250000,
        monthly_request_limit: 2000,
        monthly_token_limit: 3000000,
        max_output_tokens: 4096,
      },
    });
    await testProviderConnection("fast");
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
      "/api/settings/provider/api-key",
      expect.objectContaining({ method: "DELETE" })
    );
  });
});
