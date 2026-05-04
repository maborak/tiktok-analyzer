import { useRef, useEffect } from 'react';
import { Button } from '@/components/ui/Button';
import { Printer, X, Download } from 'lucide-react';

interface InvoiceViewerProps {
  htmlContent: string;
  invoiceNumber: string;
  onClose: () => void;
}

export function InvoiceViewer({ htmlContent, invoiceNumber, onClose }: InvoiceViewerProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    // Write HTML content to iframe when it loads
    if (iframeRef.current) {
      const iframe = iframeRef.current;
      const doc = iframe.contentDocument || iframe.contentWindow?.document;

      if (doc) {
        doc.open();
        doc.write(htmlContent);
        doc.close();

        // Add print styles
        const style = doc.createElement('style');
        style.textContent = `
          @media print {
            body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
          }
        `;
        doc.head.appendChild(style);
      }
    }
  }, [htmlContent]);

  const handlePrint = () => {
    if (iframeRef.current) {
      const iframe = iframeRef.current;
      const iframeWindow = iframe.contentWindow;

      if (iframeWindow) {
        iframeWindow.focus();
        iframeWindow.print();
      }
    }
  };

  const handleDownload = () => {
    // Create a blob from the HTML content
    const blob = new Blob([htmlContent], { type: 'text/html' });
    const url = URL.createObjectURL(blob);

    // Create a temporary link and trigger download
    const link = document.createElement('a');
    link.href = url;
    link.download = `invoice-${invoiceNumber}.html`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    // Clean up
    URL.revokeObjectURL(url);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-4xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Factura {invoiceNumber}</h2>
            <p className="text-sm text-gray-500">Ver, imprimir o descargar tu factura</p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              onClick={handleDownload}
              className="flex items-center"
            >
              <Download className="w-4 h-4 mr-2" />
              Descargar
            </Button>
            <Button
              variant="secondary"
              onClick={handlePrint}
              className="flex items-center"
            >
              <Printer className="w-4 h-4 mr-2" />
              Imprimir
            </Button>
            <button
              onClick={onClose}
              className="p-2 hover:bg-gray-100 rounded-full transition-colors"
            >
              <X className="w-5 h-5 text-gray-500" />
            </button>
          </div>
        </div>

        {/* Invoice Content */}
        <div className="flex-1 overflow-hidden bg-gray-100 p-4">
          <iframe
            ref={iframeRef}
            title={`Invoice ${invoiceNumber}`}
            className="w-full h-full bg-white rounded shadow-sm"
            style={{ minHeight: '500px' }}
          />
        </div>
      </div>
    </div>
  );
}
