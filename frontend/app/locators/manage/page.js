"use client";

import { Suspense, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";

export default function LocatorManagePage() {
  return (
    <Suspense fallback={<p className="p-10 text-sm text-zinc-500">Loading...</p>}>
      <LocatorManagePageInner />
    </Suspense>
  );
}

function LocatorManagePageInner() {
  const searchParams = useSearchParams();
  const fileInputRef = useRef(null);
  const javaPOInputRef = useRef(null);
  const [transactionNumber, setTransactionNumber] = useState(searchParams.get("transaction_number") ?? "1060");
  const [versions, setVersions] = useState([]);
  const [selectedVersionIds, setSelectedVersionIds] = useState(new Set());
  const [entries, setEntries] = useState([]);
  const [usageStats, setUsageStats] = useState({});
  const [edits, setEdits] = useState({});
  const [featureText, setFeatureText] = useState("");
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [javaScreenName, setJavaScreenName] = useState("");
  const [javaUploading, setJavaUploading] = useState(false);
  const [javaSuccess, setJavaSuccess] = useState(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [versionData, entryData, statsData] = await Promise.all([
        api.getLocatorVersions(transactionNumber),
        api.listAllLocators(transactionNumber),
        api.getLocatorUsageStats(transactionNumber),
      ]);
      setVersions(versionData);
      setEntries(entryData);
      setUsageStats(Object.fromEntries(statsData.map((s) => [s.entry_id, s])));
      setSelectedVersionIds(new Set());
      setEdits(
        Object.fromEntries(
          entryData.map((e) => [e.id, { priority_locator: e.priority_locator ?? "", fallback_locator: e.fallback_locator ?? "" }])
        )
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  async function handleUpload(fileList) {
    if (!fileList || fileList.length === 0) return;
    setError(null);
    try {
      await api.uploadLocatorFiles(Array.from(fileList));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    }
  }

  async function handleJavaPOUpload(fileList) {
    if (!fileList || fileList.length === 0) return;
    if (!javaScreenName.trim()) {
      setError("Screen name is required for Java PO upload.");
      return;
    }
    setError(null);
    setJavaSuccess(null);
    setJavaUploading(true);
    try {
      const results = await api.uploadJavaPO(fileList[0], transactionNumber, javaScreenName.trim());
      setJavaSuccess(`Imported ${results.length} version(s) from ${fileList[0].name}`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Java PO upload failed");
    } finally {
      setJavaUploading(false);
      if (javaPOInputRef.current) javaPOInputRef.current.value = "";
    }
  }

  async function handleActivate(versionId) {
    try {
      await api.activateLocatorVersion(versionId, transactionNumber);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to activate version");
    }
  }

  function toggleVersionSelected(versionId) {
    setSelectedVersionIds((prev) => {
      const next = new Set(prev);
      if (next.has(versionId)) next.delete(versionId);
      else next.add(versionId);
      return next;
    });
  }

  async function handleMergeSelected() {
    if (selectedVersionIds.size < 2) {
      setError("Select at least 2 versions to merge.");
      return;
    }
    setError(null);
    try {
      await api.mergeLocatorVersions(transactionNumber, Array.from(selectedVersionIds));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Merge failed");
    }
  }

  async function handleSaveEntry(entryId) {
    const edit = edits[entryId];
    try {
      await api.updateLocatorEntry(entryId, {
        priority_locator: edit.priority_locator,
        fallback_locator: edit.fallback_locator || null,
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save entry");
    }
  }

  async function handleDeleteEntry(entryId) {
    try {
      await api.deleteLocatorEntry(entryId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete entry");
    }
  }

  async function handleValidate() {
    setError(null);
    try {
      const result = await api.validateLocatorRepository(transactionNumber, [featureText]);
      setReport(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Validation failed");
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">Locator Repository Management</h1>
      <p className="mb-6 text-sm text-zinc-500">
        Upload locator files (JSON, Excel, CSV, XML, YAML), manage versions, merge repositories, edit entries,
        review usage statistics, and validate a repository against feature files before execution.
      </p>

      <div className="mb-6 flex items-end gap-2">
        <div className="flex flex-col gap-2">
          <Label htmlFor="transaction_number">Transaction Number</Label>
          <Input id="transaction_number" value={transactionNumber} onChange={(e) => setTransactionNumber(e.target.value)} className="w-56" />
        </div>
        <Button onClick={load} disabled={loading}>
          {loading ? "Loading..." : "Load"}
        </Button>
      </div>

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Upload, Versions &amp; Merge</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".json,.xlsx,.csv,.xml,.yaml,.yml"
              className="hidden"
              onChange={(e) => handleUpload(e.target.files)}
            />
            <input
              ref={javaPOInputRef}
              type="file"
              accept=".java"
              className="hidden"
              onChange={(e) => handleJavaPOUpload(e.target.files)}
            />
            <div className="flex gap-2">
              <Button type="button" variant="outline" onClick={() => fileInputRef.current?.click()}>
                Upload Locator File(s)
              </Button>
              <Button type="button" variant="outline" onClick={handleMergeSelected} disabled={selectedVersionIds.size < 2}>
                Merge Selected ({selectedVersionIds.size})
              </Button>
            </div>

            <div className="rounded-md border border-zinc-200 bg-zinc-50 p-3 flex flex-col gap-2">
              <p className="text-xs font-medium text-zinc-700">Import from Java Page Object (.java)</p>
              <p className="text-xs text-zinc-500">
                Upload your existing Selenium Java PO file directly — locators are extracted and
                added to the repository for transaction <strong>{transactionNumber}</strong> automatically.
              </p>
              <div className="flex flex-col gap-1">
                <Label htmlFor="java_screen_name" className="text-xs">Screen Name</Label>
                <Input
                  id="java_screen_name"
                  placeholder="e.g. Cash Withdrawal"
                  value={javaScreenName}
                  onChange={(e) => setJavaScreenName(e.target.value)}
                  className="h-7 text-xs"
                />
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={javaUploading || !javaScreenName.trim()}
                onClick={() => javaPOInputRef.current?.click()}
              >
                {javaUploading ? "Importing..." : "Choose .java File & Import"}
              </Button>
              {javaSuccess && <p className="text-xs text-emerald-600">{javaSuccess}</p>}
            </div>

            {versions.length > 0 && (
              <ul className="flex flex-col gap-2">
                {versions.map((v) => (
                  <li key={v.id} className="flex items-center justify-between rounded-md border p-2 text-sm">
                    <span className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={selectedVersionIds.has(v.id)}
                        onChange={() => toggleVersionSelected(v.id)}
                        className="h-4 w-4"
                      />
                      <Badge variant="outline">v{v.version_number}</Badge>
                      {v.source_filename}
                      <span className="text-zinc-400">({v.source_format})</span>
                    </span>
                    {v.is_active ? (
                      <Badge className="bg-emerald-100 text-emerald-800">active</Badge>
                    ) : (
                      <Button size="xs" variant="ghost" onClick={() => handleActivate(v.id)}>
                        Set Active (rollback)
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Validate Against a Feature File</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <Textarea
              placeholder="Paste Gherkin feature file text here..."
              value={featureText}
              onChange={(e) => setFeatureText(e.target.value)}
              rows={8}
            />
            <Button onClick={handleValidate} className="self-start">
              Run Validation
            </Button>

            {report && (
              <div className="mt-2 flex flex-col gap-2 rounded-md border p-3 text-sm">
                <p>
                  <span className="font-medium">{report.mapped_count}</span> / {report.total_steps} steps mapped —
                  average confidence <span className="font-medium">{Math.round(report.average_confidence * 100)}%</span>
                </p>
                {report.missing_fields.length > 0 && (
                  <p className="text-red-600">Missing: {report.missing_fields.join(", ")}</p>
                )}
                {report.invalid_locators.length > 0 && (
                  <p className="text-red-600">
                    Invalid: {report.invalid_locators.map((i) => i.field_name).join(", ")}
                  </p>
                )}
                {report.duplicate_entries.length > 0 && (
                  <p className="text-amber-600">
                    Duplicates: {report.duplicate_entries.map((d) => d.field_name).join(", ")}
                  </p>
                )}
                {report.suggested_fixes.length > 0 && (
                  <ul className="list-disc pl-5 text-zinc-600">
                    {report.suggested_fixes.map((fix, i) => (
                      <li key={i}>{fix}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Separator className="my-6" />

      <h2 className="mb-3 text-lg font-medium">Locator Entries</h2>
      {entries.length === 0 ? (
        <p className="text-sm text-zinc-500">No entries loaded. Click &quot;Load&quot; above.</p>
      ) : (
        <div className="overflow-hidden rounded-md border bg-white">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Field</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Priority Locator</TableHead>
                <TableHead>Fallback Locator</TableHead>
                <TableHead>Uses</TableHead>
                <TableHead>Heals</TableHead>
                <TableHead>Stability</TableHead>
                <TableHead>Last Success</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((entry) => {
                const stats = usageStats[entry.id];
                return (
                  <TableRow key={entry.id}>
                    <TableCell className="font-medium">{entry.field_name}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{entry.source}</Badge>
                    </TableCell>
                    <TableCell>
                      <Input
                        className="h-8 font-mono text-xs"
                        value={edits[entry.id]?.priority_locator ?? ""}
                        onChange={(e) =>
                          setEdits((prev) => ({ ...prev, [entry.id]: { ...prev[entry.id], priority_locator: e.target.value } }))
                        }
                      />
                    </TableCell>
                    <TableCell>
                      <Input
                        className="h-8 font-mono text-xs"
                        value={edits[entry.id]?.fallback_locator ?? ""}
                        onChange={(e) =>
                          setEdits((prev) => ({ ...prev, [entry.id]: { ...prev[entry.id], fallback_locator: e.target.value } }))
                        }
                      />
                    </TableCell>
                    <TableCell className="text-sm">
                      {stats ? `${stats.passed_uses}/${stats.total_uses} pass` : "-"}
                    </TableCell>
                    <TableCell className="text-sm">{stats?.heal_count ?? "-"}</TableCell>
                    <TableCell className="text-sm">
                      {stats ? (
                        <Badge className={stats.stability_score >= 0.9 ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}>
                          {Math.round(stats.stability_score * 100)}%
                        </Badge>
                      ) : (
                        "-"
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-zinc-500">
                      {stats?.last_successful_at ? new Date(stats.last_successful_at).toLocaleString() : "-"}
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        <Button size="xs" variant="outline" onClick={() => handleSaveEntry(entry.id)}>
                          Save
                        </Button>
                        <Button size="xs" variant="ghost" onClick={() => handleDeleteEntry(entry.id)}>
                          Delete
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
