import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { App } from "./App";
import { createProject, getProject, listProjects } from "./api";
import { ProjectWorkspaceView } from "./components/ProjectWorkspaceView";
import type { ProjectDetail, ProjectSummary } from "./types";

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
