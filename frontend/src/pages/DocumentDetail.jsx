import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  BookOpen,
  FileText,
  Loader2,
  MessageSquare,
  MoreVertical,
  PanelLeft,
  PanelRight,
  Plus,
  Search,
  Send,
  Sparkles,
  User,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { mapApiDocument, mapApiDocuments } from "@/lib/documentMapper";

const statusLabel = {
  uploaded: "Mới tải lên",
  processing: "Đang xử lý",
  processed: "Sẵn sàng",
  failed: "Lỗi xử lý",
};

function NotebookLogo() {
  return (
    <div className="flex h-12 w-12 items-center justify-center rounded-full bg-black text-white">
      <FileText className="h-6 w-6" />
    </div>
  );
}

function SourceItem({ doc, active, onSelect }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(doc)}
      className={`block rounded-lg border p-3 transition hover:border-zinc-500 ${
        active ? "border-zinc-900 bg-zinc-50" : "border-zinc-200 bg-white"
      }`}
    >
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-[#eef1fb] text-violet-700">
          <FileText className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-zinc-900">{doc.title}</p>
          <p className="mt-1 text-xs text-zinc-500">{doc.type || "FILE"} · {statusLabel[doc.status] || doc.status}</p>
        </div>
      </div>
    </button>
  );
}

export default function DocumentDetailPage() {
  const { id, workspaceId } = useParams();
  const navigate = useNavigate();
  const emptyDocument = useMemo(
    () => ({
      id: null,
      title: "Untitled notebook",
      filename: "Chưa có nguồn",
      abstract: "Thêm nguồn ở cột trái để bắt đầu hỏi đáp và tóm tắt.",
      status: "uploaded",
      authors: [],
      topics: [],
      updated: "",
    }),
    [],
  );

  const [document, setDocument] = useState(emptyDocument);
  const [workspace, setWorkspace] = useState(null);
  const [sources, setSources] = useState([]);
  const [qaItems, setQaItems] = useState([]);
  const [summary, setSummary] = useState(null);
  const [recommendations, setRecommendations] = useState([]);
  const [question, setQuestion] = useState("");
  const [sourceQuery, setSourceQuery] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");
  const [loading, setLoading] = useState(true);
  const [recommendationMode, setRecommendationMode] = useState("author");

  useEffect(() => {
    loadWorkspace();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, workspaceId]);

  async function loadWorkspace() {
    setLoading(true);
    setMessage("");
    if (workspaceId) {
      const workspaceResponse = await Promise.allSettled([api.getWorkspace(workspaceId)]);
      if (workspaceResponse[0].status !== "fulfilled") {
        setMessage("Không tải được phiên làm việc. Bạn cần đăng nhập lại hoặc kiểm tra backend.");
        setLoading(false);
        return;
      }

      const nextWorkspace = workspaceResponse[0].value;
      const workspaceDocuments = mapApiDocuments(nextWorkspace.documents || [], []);
      const currentDocument =
        workspaceDocuments.find((item) => String(item.id) === String(document?.id)) ||
        workspaceDocuments[0];

      setWorkspace(nextWorkspace);
      setSources(workspaceDocuments);

      if (!currentDocument) {
        setDocument({
          ...emptyDocument,
          id: null,
          title: nextWorkspace.title || "Untitled notebook",
        });
        setQaItems([]);
        setSummary(null);
        setRecommendations([]);
        setLoading(false);
        return;
      }

      setDocument(currentDocument);
      await loadDocumentFeatures(currentDocument.id);
      setLoading(false);
      return;
    }

    const [docsResponse, docResponse, qaResponse, summaryResponse, recResponse] =
      await Promise.allSettled([
        api.listDocuments({ page_size: 50 }),
        api.getDocument(id),
        api.getQaHistory(id),
        api.getSummary(id),
        api.getRecommendations(id),
      ]);

    if (docsResponse.status === "fulfilled") setSources(mapApiDocuments(docsResponse.value, []));
    if (docResponse.status === "fulfilled") setDocument(mapApiDocument(docResponse.value));
    if (qaResponse.status === "fulfilled" && qaResponse.value?.length) {
      setQaItems(
        qaResponse.value.map((item) => ({
          question: item.question,
          answer: item.answer,
          source: item.sources || "Nguồn đã chọn",
        })),
      );
    }
    if (summaryResponse.status === "fulfilled") setSummary(summaryResponse.value);
    if (recResponse.status === "fulfilled") setRecommendations(recResponse.value.items || []);

    if (docResponse.status === "rejected") {
      setMessage("Không tải được tài liệu. Bạn cần đăng nhập lại hoặc kiểm tra backend.");
    }
    setLoading(false);
  }

  async function loadDocumentFeatures(documentId) {
    const [qaResponse, summaryResponse, recResponse] = await Promise.allSettled([
      api.getQaHistory(documentId),
      api.getSummary(documentId),
      api.getRecommendations(documentId),
    ]);

    if (qaResponse.status === "fulfilled" && qaResponse.value?.length) {
      setQaItems(
        qaResponse.value.map((item) => ({
          question: item.question,
          answer: item.answer,
          source: item.sources || "Nguồn đã chọn",
        })),
      );
    } else {
      setQaItems([]);
    }
    setSummary(summaryResponse.status === "fulfilled" ? summaryResponse.value : null);
    setRecommendations(recResponse.status === "fulfilled" ? recResponse.value.items || [] : []);
  }

  async function handleUploadSource(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy("upload");
    setMessage("");
    try {
      const response = await api.uploadDocument(file, workspaceId || null);
      setMessage("Đã tải nguồn mới lên backend.");
      if (response.document_id) {
        if (workspaceId) {
          await loadWorkspace();
        } else {
          navigate(`/document/${response.document_id}`);
        }
      }
    } catch (err) {
      setMessage(err.message || "Không tải được nguồn.");
    } finally {
      setBusy("");
      event.target.value = "";
    }
  }

  async function handleRequestSummary(level) {
    if (!document.id) return;
    setBusy(`summary-${level}`);
    try {
      const response = await api.requestSummary(document.id, level);
      setMessage(`Đã tạo job tóm tắt #${response.job_id}.`);
    } catch (err) {
      setMessage(err.message || "Không tạo được job tóm tắt.");
    } finally {
      setBusy("");
    }
  }

  async function handleAskQuestion() {
    const cleanQuestion = question.trim();
    if (!cleanQuestion) return;
    if (!document.id) return;
    setBusy("qa");
    try {
      const response = await api.requestQuestion(document.id, cleanQuestion);
      setMessage(`Đã gửi câu hỏi tới AI worker. Job #${response.job_id}.`);
      setQaItems((items) => [
        {
          question: cleanQuestion,
          answer: "Đang chờ AI worker xử lý. Tải lại lịch sử sau khi job hoàn tất.",
          source: document.title,
        },
        ...items,
      ]);
      setQuestion("");
    } catch (err) {
      setMessage(err.message || "Không gửi được câu hỏi.");
    } finally {
      setBusy("");
    }
  }

  const filteredSources = sources.filter((doc) =>
    `${doc.title} ${doc.filename} ${doc.topics?.join(" ")}`.toLowerCase().includes(sourceQuery.toLowerCase()),
  );
  const groupedRecommendations = useMemo(() => {
    const authorKeywords = ["author", "tác giả", "cùng tác giả", "same author"];
    const methodKeywords = ["method", "phương pháp", "mô hình", "approach", "rag", "retrieval", "graph", "embedding"];

    return recommendations.reduce(
      (acc, item) => {
        const haystack = `${item.title || ""} ${item.reason || ""}`.toLowerCase();
        if (authorKeywords.some((keyword) => haystack.includes(keyword))) {
          acc.author.push(item);
        } else if (methodKeywords.some((keyword) => haystack.includes(keyword))) {
          acc.method.push(item);
        } else {
          acc.method.push(item);
        }
        return acc;
      },
      { author: [], method: [] },
    );
  }, [recommendations]);
  const activeRecommendations = groupedRecommendations[recommendationMode] || [];
  const sourceCount = sources.length;
  const notebookTitle = workspace?.title || document.title || "Untitled notebook";

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#eef1fb] text-zinc-700">
        <div className="flex items-center gap-3 rounded-lg border border-zinc-200 bg-white px-4 py-3">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span>Đang tải notebook...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#eef1fb] text-zinc-950">
      <header className="flex h-[84px] items-center justify-between px-6">
        <div className="flex min-w-0 items-center gap-5">
          <Link to="/home" aria-label="Về trang sổ ghi chú">
            <NotebookLogo />
          </Link>
          <h1 className="truncate text-2xl font-medium">{notebookTitle}</h1>
          <Badge variant="secondary">{statusLabel[document.status] || document.status}</Badge>
        </div>
        <div className="flex items-center gap-3">
          <label className="hidden h-10 cursor-pointer items-center rounded-full bg-black px-6 text-sm font-medium text-white hover:bg-zinc-800 md:inline-flex">
            <Plus className="mr-2 h-5 w-5" />
            Thêm nguồn
            <input
              type="file"
              accept=".pdf,.docx,.txt,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              className="hidden"
              onChange={handleUploadSource}
            />
          </label>
          <Link to="/profile" className="flex h-11 w-11 items-center justify-center rounded-full bg-violet-600 text-white">
            <User className="h-5 w-5" />
          </Link>
        </div>
      </header>

      <main className="grid min-h-[calc(100vh-84px)] gap-5 px-5 pb-5 xl:h-[calc(100vh-84px)] xl:grid-cols-[360px_minmax(460px,1fr)_420px]">
        <aside className="flex flex-col rounded-lg bg-white xl:min-h-0 xl:overflow-hidden">
          <div className="flex h-16 shrink-0 items-center justify-between border-b border-zinc-200 px-5">
            <h2 className="text-lg font-medium">Nguồn tài liệu</h2>
            <PanelLeft className="h-5 w-5 text-zinc-600" />
          </div>

          <div className="flex-1 p-5 xl:min-h-0 xl:overflow-y-auto">
            <label className="flex h-12 w-full cursor-pointer items-center justify-center rounded-full border border-zinc-300 bg-white text-sm font-medium hover:border-zinc-600">
              {busy === "upload" ? <Loader2 className="mr-3 h-5 w-5 animate-spin" /> : <Plus className="mr-3 h-5 w-5" />}
              Thêm nguồn
              <input
                type="file"
                accept=".pdf,.docx,.txt,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                className="hidden"
                onChange={handleUploadSource}
              />
            </label>

            <div className="mt-5 rounded-2xl border border-zinc-200 bg-zinc-50 p-4">
              <div className="relative">
                <Search className="absolute left-3 top-3 h-5 w-5 text-zinc-500" />
                <input
                  value={sourceQuery}
                  onChange={(event) => setSourceQuery(event.target.value)}
                  className="h-11 w-full bg-transparent pl-10 text-base outline-none"
                  placeholder="Tìm trong nguồn đã tải"
                />
              </div>
            </div>

            <div className="mt-5 space-y-3">
              {filteredSources.map((doc) => (
                <SourceItem
                  key={doc.id}
                  doc={doc}
                  active={String(doc.id) === String(document.id)}
                  onSelect={(nextDocument) => {
                    setDocument(nextDocument);
                    loadDocumentFeatures(nextDocument.id);
                  }}
                />
              ))}
            </div>

            <div className="mt-6 border-t border-zinc-200 pt-5">
              <div className="flex items-center gap-2">
                <BookOpen className="h-4 w-4 text-zinc-700" />
                <h3 className="font-medium">Gợi ý tài liệu</h3>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setRecommendationMode("author")}
                  className={`rounded-full px-3 py-2 text-sm font-medium transition ${
                    recommendationMode === "author"
                      ? "bg-zinc-900 text-white"
                      : "border border-zinc-200 bg-white text-zinc-700 hover:border-zinc-400"
                  }`}
                >
                  Theo tác giả
                </button>
                <button
                  type="button"
                  onClick={() => setRecommendationMode("method")}
                  className={`rounded-full px-3 py-2 text-sm font-medium transition ${
                    recommendationMode === "method"
                      ? "bg-zinc-900 text-white"
                      : "border border-zinc-200 bg-white text-zinc-700 hover:border-zinc-400"
                  }`}
                >
                  Theo method
                </button>
              </div>
              <div className="mt-3 space-y-3">
                {activeRecommendations.length ? activeRecommendations.map((item) => (
                  <div key={item.id || item.title} className="rounded-lg bg-zinc-50 p-3">
                    <p className="text-sm font-medium text-zinc-900">{item.title}</p>
                    <p className="mt-1 text-xs leading-5 text-zinc-500">{item.reason || "Không có lý do gợi ý."}</p>
                  </div>
                )) : (
                  <div className="rounded-lg border border-dashed border-zinc-300 p-4 text-sm leading-6 text-zinc-500">
                    {recommendations.length
                      ? `Chưa có gợi ý ${recommendationMode === "author" ? "theo tác giả" : "theo method"}.`
                      : "Chưa có gợi ý từ backend. Hãy xử lý AI sau khi thêm nguồn."}
                  </div>
                )}
              </div>
            </div>
          </div>
        </aside>

        <section className="flex flex-col rounded-lg bg-white xl:min-h-0 xl:overflow-hidden">
          <div className="flex h-16 shrink-0 items-center justify-between border-b border-zinc-200 px-5">
            <h2 className="text-lg font-medium">Cuộc trò chuyện</h2>
            <MoreVertical className="h-5 w-5 text-zinc-600" />
          </div>

          <div className="flex-1 px-7 py-8 xl:min-h-0 xl:overflow-y-auto">
            {message && <div className="mb-5 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">{message}</div>}
            <div className="mx-auto max-w-3xl">
              <div className="flex h-16 w-16 items-center justify-center rounded-lg bg-[#eef1fb] text-violet-700">
                <BookOpen className="h-8 w-8" />
              </div>
              <h3 className="mt-12 text-4xl font-medium tracking-normal">{notebookTitle}</h3>
              <p className="mt-3 text-lg text-zinc-700">{sourceCount} nguồn · {document.updated || "chưa rõ thời gian"}</p>
              <p className="mt-5 text-sm leading-6 text-zinc-600">
                {document.id ? `Nguồn đang chọn: ${document.title}. ${document.abstract}` : document.abstract}
              </p>

              <div className="mt-10 space-y-4">
                {qaItems.map((item) => (
                  <div key={`${item.question}-${item.answer}`} className="rounded-lg border border-zinc-200 p-5">
                    <div className="flex items-start gap-2">
                      <MessageSquare className="mt-0.5 h-4 w-4 text-zinc-700" />
                      <p className="font-medium">{item.question}</p>
                    </div>
                    <p className="mt-3 text-sm leading-6 text-zinc-600">{item.answer}</p>
                    <Badge variant="secondary" className="mt-3">Nguồn: {item.source}</Badge>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="shrink-0 px-7 pb-5">
            <div className="mx-auto flex max-w-5xl items-center gap-4 rounded-2xl border border-zinc-400 bg-white p-3 shadow-sm">
              <input
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") handleAskQuestion();
                }}
                className="h-14 min-w-0 flex-1 px-4 text-base outline-none"
                placeholder="Hỏi về tài liệu này..."
              />
              <span className="hidden text-sm text-zinc-600 sm:inline">
                {document?.id ? "1 nguồn đang chọn" : "Chưa chọn nguồn"}
              </span>
              <Button onClick={handleAskQuestion} disabled={busy === "qa" || !document.id} size="icon" className="h-12 w-12 rounded-full bg-zinc-200 text-zinc-700 hover:bg-zinc-300">
                {busy === "qa" ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
              </Button>
            </div>
            <p className="mt-3 text-center text-xs text-zinc-500">
              Câu hỏi được gửi tới `POST /api/v1/cms/documents/{id}/qa/request`; kết quả thật lấy từ lịch sử Q&A sau khi AI worker ghi về backend.
            </p>
          </div>
        </section>

        <aside className="flex flex-col rounded-lg bg-white xl:min-h-0 xl:overflow-hidden">
          <div className="flex h-16 shrink-0 items-center justify-between border-b border-zinc-200 px-5">
            <h2 className="text-lg font-medium">Studio</h2>
            <PanelRight className="h-5 w-5 text-zinc-600" />
          </div>

          <div className="flex-1 p-5 xl:min-h-0 xl:overflow-y-auto">
            <section className="rounded-2xl border border-zinc-200 bg-zinc-50 p-5">
              <div className="flex items-center justify-between gap-3 text-zinc-900">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-5 w-5" />
                  <p className="text-sm font-medium">Tóm tắt</p>
                </div>
                <Button
                  onClick={() => handleRequestSummary("medium")}
                  disabled={!document.id || busy === "summary-medium"}
                  className="rounded-full bg-zinc-900 px-4 text-sm font-medium text-white hover:bg-zinc-800"
                >
                  {busy === "summary-medium" ? <Loader2 className="h-4 w-4 animate-spin" /> : "Tạo tóm tắt"}
                </Button>
              </div>
              <p className="mt-3 text-sm leading-7 text-zinc-600">
                {summary?.summary_medium || summary?.summary_short || summary?.summary_long || "Chưa có tóm tắt trong backend. Hãy bấm Tóm tắt để tạo nội dung đầu ra."}
              </p>
            </section>
          </div>
        </aside>
      </main>
    </div>
  );
}
