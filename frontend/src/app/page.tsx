"use client";

import { useState, useEffect } from "react";

export default function Home() {
  const [url, setUrl] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [status, setStatus] = useState("");
  const [previewUrl, setPreviewUrl] = useState("");
  const [error, setError] = useState("");
  const [instruction, setInstruction] = useState("");
  const [modifyImage, setModifyImage] = useState<File | null>(null);
  
  const API_URL = "http://localhost:8000";

  const handleGenerate = async () => {
    setError("");
    setSessionId("");
    setStatus("pending");
    setPreviewUrl("");
    try {
      const res = await fetch(`${API_URL}/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url })
      });
      if (!res.ok) throw new Error("Failed to start generation");
      const data = await res.json();
      setSessionId(data.session_id);
    } catch (err: any) {
      setError(err.message);
      setStatus("");
    }
  };

  const handleModify = async () => {
    if (!sessionId || (!instruction && !modifyImage)) return;
    setStatus("modifying");
    setError("");
    try {
      const formData = new FormData();
      formData.append("instruction", instruction);
      if (modifyImage) {
        formData.append("image", modifyImage);
      }

      const res = await fetch(`${API_URL}/modify/${sessionId}`, {
        method: "POST",
        body: formData
      });
      if (!res.ok) throw new Error("Failed to start modification");
      setInstruction("");
      setModifyImage(null);
    } catch (err: any) {
      setError(err.message);
      setStatus("error");
    }
  };

  useEffect(() => {
    if (!sessionId) return;
    
    let interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_URL}/status/${sessionId}`);
        const data = await res.json();
        
        setStatus(data.status);
        
        if (data.status === "error") {
          setError(data.error);
          clearInterval(interval);
        } else if (data.status === "complete") {
          setPreviewUrl(data.preview_url);
        }
      } catch (err) {
        console.error("Error polling status", err);
      }
    }, 2000);
    
    return () => clearInterval(interval);
  }, [sessionId]);

  return (
    <div className="flex flex-col min-h-screen bg-gray-50 text-gray-900 font-sans">
      <header className="p-4 bg-white border-b shadow-sm flex items-center justify-between">
        <h1 className="text-xl font-bold text-blue-600">AI Website Cloner</h1>
        <div className="flex gap-2 w-1/2">
          <input 
            type="text" 
            placeholder="Enter website URL..." 
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="border p-2 rounded flex-1 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button 
            onClick={handleGenerate}
            className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 transition"
            disabled={!url || (status !== "" && status !== "complete" && status !== "error")}
          >
            Generate
          </button>
        </div>
      </header>

      <main className="flex-1 p-4 flex flex-col items-center">
        {error && (
          <div className="w-full max-w-4xl p-4 mb-4 bg-red-100 text-red-700 rounded-md">
            <strong>Error:</strong> {error}
          </div>
        )}
        
        {status && status !== "complete" && status !== "error" && (
          <div className="flex flex-col items-center justify-center py-20">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mb-4"></div>
            <p className="text-lg font-medium text-gray-700 capitalize">
              {status.replace(/_/g, ' ')}...
            </p>
          </div>
        )}
        
        {status === "complete" && previewUrl && (
          <div className="w-full h-full flex flex-col border bg-white shadow-sm rounded-lg overflow-hidden" style={{ minHeight: '70vh' }}>
            <div className="bg-gray-100 px-4 py-2 border-b flex items-center text-sm text-gray-500">
              <span className="w-3 h-3 rounded-full bg-red-400 mr-2"></span>
              <span className="w-3 h-3 rounded-full bg-yellow-400 mr-2"></span>
              <span className="w-3 h-3 rounded-full bg-green-400 mr-4"></span>
              Preview: <a href={previewUrl} target="_blank" rel="noreferrer" className="ml-2 text-blue-500 hover:underline">{previewUrl}</a>
            </div>
            <iframe 
              src={previewUrl} 
              className="w-full flex-1 border-0" 
              title="Preview"
            />
          </div>
        )}
      </main>
      
      {status === "complete" && (
        <footer className="p-4 bg-white border-t flex flex-col gap-2">
          {modifyImage && (
            <div className="flex items-center gap-2 mb-2 p-2 border rounded bg-gray-50 w-max">
              <img src={URL.createObjectURL(modifyImage)} alt="Preview" className="h-16 w-16 object-cover rounded border" />
              <button onClick={() => setModifyImage(null)} className="text-red-500 hover:text-red-700 p-1" title="Remove image">
                <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                </svg>
              </button>
            </div>
          )}
          <div className="flex items-center gap-2">
            <label className="cursor-pointer p-2 text-gray-500 hover:text-blue-600 hover:bg-gray-100 rounded transition" title="Upload an image">
              <input 
                type="file" 
                className="hidden" 
                accept="image/*"
                onChange={(e) => {
                  if (e.target.files && e.target.files[0]) {
                    setModifyImage(e.target.files[0]);
                    e.target.value = '';
                  }
                }}
              />
              <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
            </label>
            <input 
              type="text" 
              placeholder="Ask for modifications (e.g. 'change the hero background to blue')" 
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              className="border p-2 rounded flex-1 focus:outline-none focus:ring-2 focus:ring-blue-500"
              onKeyDown={(e) => e.key === 'Enter' && handleModify()}
            />
            <button 
              onClick={handleModify}
              className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700 transition"
              disabled={!instruction && !modifyImage}
            >
              Modify
            </button>
          </div>
        </footer>
      )}
    </div>
  );
}
