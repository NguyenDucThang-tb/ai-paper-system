import { Link } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import {
  BookOpen,
  Brain,
  ChartColumn,
  FileQuestion,
  Library,
  MoreVertical,
  Plus,
  Search,
  Sparkles,
  User,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { mapApiWorkspaces } from "@/lib/workspaceMapper";

const notebookStyles = [
  { icon: BookOpen, accent: "bg-[#eef1fb]", iconColor: "text-violet-700" },
  { icon: Brain, accent: "bg-[#dff3f8]", iconColor: "text-pink-600" },
  { icon: Search, accent: "bg-[#f3f2e9]", iconColor: "text-cyan-700" },
  { icon: Sparkles, accent: "bg-[#eef1fb]", iconColor: "text-lime-600" },
  { icon: ChartColumn, accent: "bg-[#f5ecea]", iconColor: "text-blue-700" },
  { icon: Library, accent: "bg-[#e7f5f6]", iconColor: "text-emerald-700" },
];

function NotebookMark({ compact = false }) {
  return (
    <div className={`flex items-center gap-3 ${compact ? "" : "text-zinc-950"}`}>
      <div className={`${compact ? "h-10 w-10" : "h-9 w-9"} flex items-center justify-center rounded-full bg-black text-white`}>
        <FileQuestion className={compact ? "h-5 w-5" : "h-4 w-4"} />
      </div>
      {!compact && <span className="text-2xl font-semibold tracking-normal">AI PaperLM</span>}
    </div>
  );
}

function NotebookCard({ workspace, index }) {
  const style = notebookStyles[index % notebookStyles.length];
  const Icon = style.icon;

  return (
    <Link
      to={`/workspace/${workspace.id}`}
      className={`group min-h-[210px] rounded-lg p-7 text-left transition hover:-translate-y-0.5 hover:shadow-md ${style.accent}`}
    >
      <div className="flex items-start justify-between">
        <Icon className={`h-12 w-12 ${style.iconColor}`} strokeWidth={1.8} />
        <MoreVertical className="h-5 w-5 text-zinc-500" />
      </div>
      <h3 className="mt-10 line-clamp-2 text-2xl font-medium leading-tight text-zinc-950">
        {workspace.title || "Untitled notebook"}
      </h3>
      <p className="mt-5 text-sm text-zinc-600">
        {workspace.updated || "5 thg 5, 2026"} · {workspace.documentCount || 0} nguồn
      </p>
    </Link>
  );
}

export default function UserHomePage() {
  const [workspaces, setWorkspaces] = useState([]);
  const [query, setQuery] = useState("");
  const [apiNote, setApiNote] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    async function loadNotebooks() {
      try {
        const response = await api.listWorkspaces({ page_size: 12 });
        setWorkspaces(mapApiWorkspaces(response, []));
        setApiNote("");
      } catch {
        setApiNote("Không tải được phiên làm việc. Hãy đăng nhập và chạy backend.");
      }
    }
    loadNotebooks();
  }, []);

  const filteredWorkspaces = useMemo(() => {
    if (!query.trim()) return workspaces;
    return workspaces.filter((workspace) =>
      `${workspace.title} ${workspace.documents.map((doc) => doc.title).join(" ")}`.toLowerCase().includes(query.toLowerCase()),
    );
  }, [workspaces, query]);

  async function handleCreateWorkspace() {
    setCreating(true);
    setApiNote("");
    try {
      const workspace = await api.createWorkspace("Untitled notebook");
      window.location.href = `/workspace/${workspace.id}`;
    } catch (err) {
      setApiNote(err.message || "Không tạo được phiên làm việc.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="min-h-screen bg-white text-zinc-950">
      <header className="sticky top-0 z-20 border-b border-zinc-100 bg-white/95 backdrop-blur">
        <div className="flex h-20 items-center justify-between px-6 lg:px-8">
          <NotebookMark />
          <Link to="/profile" className="flex h-11 w-11 items-center justify-center rounded-full bg-violet-600 text-white">
            <User className="h-5 w-5" />
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-[1500px] px-6 py-10 lg:px-8">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative">
              <Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="h-12 w-full rounded-full border border-zinc-300 bg-white pl-11 pr-4 text-sm outline-none transition focus:border-zinc-700 md:w-72"
                placeholder="Tìm sổ ghi chú"
              />
            </div>
            <Button onClick={handleCreateWorkspace} disabled={creating} className="h-12 rounded-full bg-black px-6 text-white hover:bg-zinc-800">
              <Plus className="mr-2 h-5 w-5" />
              {creating ? "Đang tạo" : "Tạo mới"}
            </Button>
          </div>
        </div>

        <section className="mt-10">
          <h1 className="text-3xl font-medium tracking-normal">Sổ ghi chú gần đây</h1>
          {apiNote && <p className="mt-3 text-sm text-amber-700">{apiNote}</p>}
          <div className="mt-6 grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
            <button
              onClick={handleCreateWorkspace}
              disabled={creating}
              className="flex min-h-[210px] flex-col items-center justify-center rounded-lg border border-zinc-300 bg-white p-7 text-center transition hover:border-zinc-500 hover:shadow-sm"
            >
              <div className="flex h-20 w-20 items-center justify-center rounded-full bg-[#eef1fb] text-blue-600">
                <Plus className="h-8 w-8" />
              </div>
              <p className="mt-6 text-2xl font-medium">Tạo sổ ghi chú mới</p>
            </button>
            {filteredWorkspaces.map((workspace, index) => (
              <NotebookCard key={workspace.id || workspace.title} workspace={workspace} index={index} />
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}
