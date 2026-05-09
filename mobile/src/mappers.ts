import type { DocumentItem } from './api';

export type ViewDocument = {
  id: string;
  title: string;
  authors: string;
  year: string;
  status: string;
  abstract: string;
};

export function mapDocument(document: DocumentItem): ViewDocument {
  const metadata = document.metadata || {};
  return {
    id: String(document.id),
    title: metadata.title || document.filename || 'untitled',
    authors: metadata.authors?.length ? metadata.authors.join(', ') : 'Chưa có tác giả',
    year: String(metadata.publication_year || 'N/A'),
    status: document.status || 'uploaded',
    abstract: metadata.abstract || 'Chưa có mô tả.',
  };
}

export function mapDocuments(payload: any): ViewDocument[] {
  const items = Array.isArray(payload) ? payload : payload?.items || [];
  return items.map(mapDocument);
}
