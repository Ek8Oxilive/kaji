import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api, type Guest } from "../lib/api";
import { confirmReasons } from "../lib/confirmRisk";
import { AUDIO_DEVICES, BIOS, EFI_TYPES, SERIALS, TPM_VERSIONS, VGA_TYPES, WATCHDOG_ACTIONS, WATCHDOG_MODELS, type DeviceKey, type DevicesPatch, type DevicesResponse, type DevicesResult } from "../lib/types/peripheriques";
import { useStorages } from "./HardwareDialogs";
import { useToast } from "./Toast";
import { Button, Notice } from "./ui";

import { tr } from "../lib/i18n";
const intOk = (s: string, min: number, max: number) => s.trim() === "" || (/^\d+$/.test(s.trim()) && Number(s) >= min && Number(s) <= max);
const num = (s: string) => (s.trim() === "" ? null : Number(s));

/**
 * Onglet « Périphériques » (VM) : carte d'affichage, ports série (socket seulement), audio, générateur aléatoire, watchdog.
 * Le serveur relit la machine, décide des confirmations et refuse tout ce qui toucherait un périphérique de l'hôte.
 */
export function DevicesTab({ connId, guest }: { connId: number; guest: Guest }) {
  const base = `/api/connections/${connId}/guests/${encodeURIComponent(guest.node)}/qemu/${guest.vmid}/devices`;
  const qk = ["devices", connId, guest.node, guest.vmid];
  const qc = useQueryClient();
  const toast = useToast();
  const { data, error, isLoading, refetch } = useQuery({ queryKey: qk, queryFn: () => api<DevicesResponse>(base), staleTime: 0 });
  const [vgaType, setVgaType] = useState(""); const [vgaMem, setVgaMem] = useState(""); const [clip, setClip] = useState(false);
  const [serial, setSerial] = useState<Record<string, boolean>>({});
  const [audioOn, setAudioOn] = useState(false); const [audioDev, setAudioDev] = useState("ich9-intel-hda"); const [audioDrv, setAudioDrv] = useState("");
  const [rngOn, setRngOn] = useState(false); const [rngBytes, setRngBytes] = useState(""); const [rngPeriod, setRngPeriod] = useState("");
  const [wdOn, setWdOn] = useState(false); const [wdModel, setWdModel] = useState("i6300esb"); const [wdAction, setWdAction] = useState("");
  const [bios, setBios] = useState("");
  const [efiAdd, setEfiAdd] = useState(false); const [efiRemove, setEfiRemove] = useState(false); const [efiStorage, setEfiStorage] = useState(""); const [efiType, setEfiType] = useState("4m"); const [efiKeys, setEfiKeys] = useState(false);
  const [tpmAdd, setTpmAdd] = useState(false); const [tpmRemove, setTpmRemove] = useState(false); const [tpmStorage, setTpmStorage] = useState(""); const [tpmVersion, setTpmVersion] = useState("v2.0");
  const storages = useStorages(connId, guest.node, false);
  const diskStorages = (storages.data ?? []).filter((s) => s.active);
  const [cleared, setCleared] = useState<Set<DeviceKey>>(new Set());
  const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null);
  const [risk, setRisk] = useState<string[] | null>(null);

  // Remplit le formulaire avec l'état réel relu chez Proxmox.
  useEffect(() => {
    if (!data) return;
    const d = data.devices;
    setVgaType(d.vga?.type ?? ""); setVgaMem(d.vga?.memory?.toString() ?? ""); setClip(d.vga?.clipboard === "vnc");
    setSerial(Object.fromEntries(SERIALS.map((k) => [k, d[k] === "socket"])));
    setAudioOn(!!d.audio); setAudioDev(d.audio?.device ?? "ich9-intel-hda"); setAudioDrv(d.audio?.driver ?? "");
    setRngOn(!!d.rng); setRngBytes(d.rng?.max_bytes?.toString() ?? ""); setRngPeriod(d.rng?.period?.toString() ?? "");
    setWdOn(!!d.watchdog); setWdModel(d.watchdog?.model ?? "i6300esb"); setWdAction(d.watchdog?.action ?? "");
    setBios(d.bios ?? "");
    setEfiAdd(false); setEfiRemove(false); setEfiType("4m"); setEfiKeys(false); setTpmAdd(false); setTpmRemove(false); setTpmVersion("v2.0");
    setCleared(new Set()); setRisk(null);
  }, [data]);
  useEffect(() => { if (!efiStorage && diskStorages[0]) setEfiStorage(diskStorages[0].storage); if (!tpmStorage && diskStorages[0]) setTpmStorage(diskStorages[0].storage); }, [diskStorages, efiStorage, tpmStorage]);

  const valid = intOk(vgaMem, 4, 512) && intOk(rngBytes, 0, 1_000_000) && intOk(rngPeriod, 1, 3_600_000);

  /** Ne contient que ce qui a changé : le serveur ignore de toute façon ce qui est identique. */
  const patch = useMemo((): DevicesPatch | null => {
    if (!data) return null;
    const d = data.devices; const p: DevicesPatch = {}; const clear: DeviceKey[] = [];
    // carte d'affichage
    const v: NonNullable<DevicesPatch["vga"]> = {};
    if (vgaType && vgaType !== d.vga?.type) v.type = vgaType;
    if (num(vgaMem) !== null && num(vgaMem) !== d.vga?.memory) v.memory = Number(vgaMem);
    if (clip !== (d.vga?.clipboard === "vnc") && clip) v.clipboard = "vnc";
    if (Object.keys(v).length) p.vga = v;
    // ports série : seulement socket ; un port « device » (hôte) n'est pas modifiable ici
    for (const k of SERIALS) {
      if (d[k] === "device") continue;
      if (serial[k] && d[k] !== "socket") p[k] = "socket";
      if (!serial[k] && d[k] === "socket") clear.push(k);
    }
    // audio
    if (audioOn && (audioDev !== d.audio?.device || (audioDrv && audioDrv !== d.audio?.driver))) p.audio = { device: audioDev, ...(audioDrv ? { driver: audioDrv } : {}) };
    if (!audioOn && d.audio) clear.push("audio0");
    // RNG (source toujours /dev/urandom ; une source d'hôte posée par root reste en lecture seule)
    const hostSrc = !!d.rng && d.rng.source !== null && d.rng.source !== "/dev/urandom";
    if (rngOn && !hostSrc) {
      const r: NonNullable<DevicesPatch["rng"]> = {};
      if (num(rngBytes) !== null && num(rngBytes) !== d.rng?.max_bytes) r.max_bytes = Number(rngBytes);
      if (num(rngPeriod) !== null && num(rngPeriod) !== d.rng?.period) r.period = Number(rngPeriod);
      if (!d.rng || Object.keys(r).length) p.rng = r;
    }
    if (!rngOn && d.rng && !hostSrc) clear.push("rng0");
    // watchdog
    if (wdOn && (wdModel !== d.watchdog?.model || (wdAction && wdAction !== d.watchdog?.action))) p.watchdog = { model: wdModel, ...(wdAction ? { action: wdAction } : {}) };
    if (!wdOn && d.watchdog) clear.push("watchdog");
    // BIOS, disque EFI et TPM : ajout seulement si absent ; retrait confirmé par le serveur
    if (bios && bios !== (d.bios ?? "seabios")) p.bios = bios;
    if (!d.efidisk && efiAdd && efiStorage) p.efidisk = { storage: efiStorage, efitype: efiType, pre_enrolled_keys: efiKeys };
    if (d.efidisk && efiRemove) clear.push("efidisk0");
    if (!d.tpm && tpmAdd && tpmStorage) p.tpm = { storage: tpmStorage, version: tpmVersion };
    if (d.tpm && tpmRemove) clear.push("tpmstate0");
    // « Valeur par défaut » de la carte d'affichage
    if (cleared.has("vga")) { delete p.vga; clear.push("vga"); }
    if (clear.length) p.clear = [...new Set(clear)];
    return Object.keys(p).length ? p : null;
  }, [data, vgaType, vgaMem, clip, serial, audioOn, audioDev, audioDrv, rngOn, rngBytes, rngPeriod, wdOn, wdModel, wdAction, cleared, bios, efiAdd, efiRemove, efiStorage, efiType, efiKeys, tpmAdd, tpmRemove, tpmStorage, tpmVersion]);
  // Une confirmation ne vaut que pour la demande qui l'a provoquée.
  const patchKey = JSON.stringify(patch);
  useEffect(() => { setRisk(null); }, [patchKey]);

  const save = async (confirm: boolean) => {
    if (!patch) return setErr(tr("Aucune modification."));
    setBusy(true); setErr(null);
    try {
      await api<DevicesResult>(base, { method: "PATCH", body: { ...patch, ...(confirm ? { confirm: true } : {}) } });
      toast("ok", tr("Enregistré : ces réglages ne s'appliquent qu'au prochain démarrage de la VM"));
      await qc.invalidateQueries({ queryKey: qk });
    } catch (e) {
      const reasons = !confirm ? confirmReasons(e) : null;
      if (reasons) setRisk(reasons); else setErr((e as Error).message);
    } finally { setBusy(false); }
  };

  if (isLoading) return <div className="panel h-40 animate-pulse" />;
  if (error || !data) return <Notice kind="error">{(error as Error | null)?.message ?? tr("Périphériques illisibles")} — <button className="underline" onClick={() => refetch()}>{tr("réessayer")}</button></Notice>;
  const d = data.devices;
  const box = "mt-0.5 size-4 accent-[var(--accent)]";
  const hostRng = !!d.rng && d.rng.source !== null && d.rng.source !== "/dev/urandom";
  const toggleVgaDefault = () => setCleared((s) => { const n = new Set(s); if (n.has("vga")) n.delete("vga"); else n.add("vga"); return n; });

  return (
    <div className="space-y-5">
      {data.pending.length > 0 && <Notice kind="ok">{tr("Changements en attente (appliqués au prochain démarrage) : {p}.", { p: data.pending.map((p) => p.key).join(", ") })}</Notice>}
      <div className="panel space-y-3 p-5">
        <h3 className="font-semibold">{tr("Carte d'affichage")}</h3>
        <div className="grid gap-4 sm:grid-cols-3">
          <label className="block space-y-1.5"><span className="text-sm text-muted">{tr("Type")}</span>
            <select className="field" value={vgaType} onChange={(e) => setVgaType(e.target.value)} disabled={cleared.has("vga")}>
              <option value="">{tr("Par défaut (std)")}</option>{VGA_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}</select></label>
          <label className="block space-y-1.5"><span className="text-sm text-muted">{tr("Mémoire vidéo (Mo)")}</span>
            <input className="field" value={vgaMem} onChange={(e) => setVgaMem(e.target.value)} inputMode="numeric" placeholder={tr("4 à 512")} disabled={cleared.has("vga")} aria-invalid={!intOk(vgaMem, 4, 512)} /></label>
          <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" className={box} checked={clip} onChange={(e) => setClip(e.target.checked)} disabled={cleared.has("vga")} />{tr("Presse-papiers VNC")}</label>
        </div>
        <p className="text-xs text-muted">{tr("« none » ou un port série retire l'affichage de la console graphique : le serveur demande une confirmation.")}</p>
        {d.vga !== null && <button type="button" className="text-xs text-muted underline" onClick={toggleVgaDefault}>{cleared.has("vga") ? tr("Annuler") : tr("Valeur par défaut")}</button>}
      </div>
      <div className="panel space-y-3 p-5">
        <h3 className="font-semibold">{tr("Ports série")}</h3>
        <div className="flex flex-wrap gap-4">
          {SERIALS.map((k) => (
            <label key={k} className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={d[k] === "device" ? true : !!serial[k]} disabled={d[k] === "device"}
                onChange={(e) => setSerial((s) => ({ ...s, [k]: e.target.checked }))} />{k}{d[k] === "device" && <span className="text-xs text-muted">{" "}{tr("(périphérique de l'hôte : seulement dans Proxmox)")}</span>}
            </label>
          ))}
        </div>
        <p className="text-xs text-muted">{tr("Seul le mode « socket » est proposé (console série par Proxmox) ; jamais un périphérique de l'hôte.")}</p>
      </div>
      <div className="panel space-y-3 p-5">
        <h3 className="font-semibold">{tr("Audio")}</h3>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" className={box} checked={audioOn} onChange={(e) => setAudioOn(e.target.checked)} /><span>{tr("Carte son virtuelle")}</span></label>
        {audioOn && (
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block space-y-1.5"><span className="text-sm text-muted">{tr("Appareil")}</span>
              <select className="field" value={audioDev} onChange={(e) => setAudioDev(e.target.value)}>{AUDIO_DEVICES.map((a) => <option key={a}>{a}</option>)}</select></label>
            <label className="block space-y-1.5"><span className="text-sm text-muted">{tr("Pilote")}</span>
              <select className="field" value={audioDrv} onChange={(e) => setAudioDrv(e.target.value)}><option value="">{tr("Par défaut (spice)")}</option><option>{tr("spice")}</option><option>{tr("none")}</option></select></label>
          </div>
        )}
      </div>
      <div className="panel space-y-3 p-5">
        <h3 className="font-semibold">{tr("Générateur aléatoire (RNG)")}</h3>
        {hostRng && <Notice kind="error">{tr("Source d'hôte posée par root : lecture seule, à modifier dans Proxmox.")}</Notice>}
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" className={box} checked={rngOn} disabled={hostRng} onChange={(e) => setRngOn(e.target.checked)} /><span>{tr("Fournir de l'entropie à la VM")}<span className="block text-xs text-muted">{tr("Source : /dev/urandom (non modifiable).")}</span></span></label>
        {rngOn && !hostRng && (
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block space-y-1.5"><span className="text-sm text-muted">{tr("Octets max par période")}</span>
              <input className="field" value={rngBytes} onChange={(e) => setRngBytes(e.target.value)} inputMode="numeric" placeholder="1024" aria-invalid={!intOk(rngBytes, 0, 1_000_000)} /></label>
            <label className="block space-y-1.5"><span className="text-sm text-muted">{tr("Période (ms)")}</span>
              <input className="field" value={rngPeriod} onChange={(e) => setRngPeriod(e.target.value)} inputMode="numeric" placeholder="1000" aria-invalid={!intOk(rngPeriod, 1, 3_600_000)} /></label>
          </div>
        )}
      </div>
      <div className="panel space-y-3 p-5">
        <h3 className="font-semibold">{tr("Watchdog")}</h3>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" className={box} checked={wdOn} onChange={(e) => setWdOn(e.target.checked)} /><span>{tr("Watchdog matériel virtuel")}<span className="block text-xs text-muted">{tr("Le système invité doit le piloter ; sinon l'action se déclenche.")}</span></span></label>
        {wdOn && (
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block space-y-1.5"><span className="text-sm text-muted">{tr("Modèle")}</span>
              <select className="field" value={wdModel} onChange={(e) => setWdModel(e.target.value)}>{WATCHDOG_MODELS.map((m) => <option key={m}>{m}</option>)}</select></label>
            <label className="block space-y-1.5"><span className="text-sm text-muted">{tr("Action")}</span>
              <select className="field" value={wdAction} onChange={(e) => setWdAction(e.target.value)}><option value="">{tr("Par défaut (reset)")}</option>{WATCHDOG_ACTIONS.map((a) => <option key={a}>{a}</option>)}</select></label>
          </div>
        )}
      </div>
      <div className="panel space-y-4 p-5">
        <h3 className="font-semibold">{tr("Démarrage et sécurité")}</h3>
        <label className="block space-y-1.5 text-sm"><span className="text-muted">{tr("BIOS")}</span>
          <select className="field max-w-xs" value={bios} onChange={(e) => setBios(e.target.value)}>{!d.bios && <option value="">{tr("Par défaut (seabios)")}</option>}{BIOS.map((b) => <option key={b} value={b}>{b === "ovmf" ? "ovmf (UEFI)" : "seabios (BIOS classique)"}</option>)}</select>
          <span className="block text-xs text-muted">{tr("Changer le BIOS d'une machine déjà installée peut l'empêcher de démarrer : le serveur demande une confirmation.")}</span></label>
        <div className="space-y-2 border-t border-line/60 pt-3">
          <p className="text-sm font-medium">{tr("Disque EFI")}</p>
          {d.efidisk ? (
            <>
              <p className="text-sm text-muted">{tr("Présent sur")}{" "}<code>{d.efidisk.storage ?? "?"}</code>{d.efidisk.efitype ? ` · ${d.efidisk.efitype}` : ""}{d.efidisk.pre_enrolled_keys ? tr(" · clés pré-enrôlées") : ""}.</p>
              <label className="flex items-start gap-2 text-sm"><input type="checkbox" className={box} checked={efiRemove} onChange={(e) => setEfiRemove(e.target.checked)} /><span>{tr("Retirer le disque EFI")}{" "}<span className="text-xs text-muted">{tr("(le volume reste en « non utilisé » : à supprimer dans l'onglet Matériel)")}</span></span></label>
            </>
          ) : (
            <>
              <label className="flex items-start gap-2 text-sm"><input type="checkbox" className={box} checked={efiAdd} onChange={(e) => setEfiAdd(e.target.checked)} /><span>{tr("Ajouter un disque EFI")}{" "}<span className="text-xs text-muted">{tr("(nécessaire pour le BIOS ovmf)")}</span></span></label>
              {efiAdd && (
                <div className="grid gap-4 sm:grid-cols-3">
                  <label className="block space-y-1.5"><span className="text-sm text-muted">{tr("Stockage")}</span>
                    <select className="field" value={efiStorage} onChange={(e) => setEfiStorage(e.target.value)}>{diskStorages.length === 0 && <option value="">{tr("Aucun stockage de disques")}</option>}{diskStorages.map((s) => <option key={s.storage} value={s.storage}>{s.storage}</option>)}</select></label>
                  <label className="block space-y-1.5"><span className="text-sm text-muted">{tr("Taille des variables")}</span>
                    <select className="field" value={efiType} onChange={(e) => setEfiType(e.target.value)}>{EFI_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}</select></label>
                  <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" className="size-4 accent-[var(--accent)]" checked={efiKeys} onChange={(e) => setEfiKeys(e.target.checked)} />{tr("Clés pré-enrôlées (Secure Boot)")}</label>
                </div>
              )}
            </>
          )}
        </div>
        <div className="space-y-2 border-t border-line/60 pt-3">
          <p className="text-sm font-medium">{tr("TPM")}</p>
          {d.tpm ? (
            <>
              <p className="text-sm text-muted">{tr("Présent sur")}{" "}<code>{d.tpm.storage ?? "?"}</code>{d.tpm.version ? ` · ${d.tpm.version}` : ""}.</p>
              <label className="flex items-start gap-2 text-sm"><input type="checkbox" className={box} checked={tpmRemove} onChange={(e) => setTpmRemove(e.target.checked)} /><span>{tr("Retirer le TPM")}{" "}<span className="text-xs text-muted">{tr("(son état est détaché ; le volume reste en « non utilisé »)")}</span></span></label>
            </>
          ) : (
            <>
              <label className="flex items-start gap-2 text-sm"><input type="checkbox" className={box} checked={tpmAdd} onChange={(e) => setTpmAdd(e.target.checked)} /><span>{tr("Ajouter un TPM virtuel")}</span></label>
              {tpmAdd && (
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="block space-y-1.5"><span className="text-sm text-muted">{tr("Stockage de l'état")}</span>
                    <select className="field" value={tpmStorage} onChange={(e) => setTpmStorage(e.target.value)}>{diskStorages.length === 0 && <option value="">{tr("Aucun stockage de disques")}</option>}{diskStorages.map((s) => <option key={s.storage} value={s.storage}>{s.storage}</option>)}</select></label>
                  <label className="block space-y-1.5"><span className="text-sm text-muted">{tr("Version")}</span>
                    <select className="field" value={tpmVersion} onChange={(e) => setTpmVersion(e.target.value)}>{TPM_VERSIONS.map((v) => <option key={v} value={v}>{v}</option>)}</select></label>
                </div>
              )}
            </>
          )}
        </div>
      </div>
      {risk && (
        <div className="space-y-2 rounded-xl border border-warn/40 bg-warn/10 p-3 text-sm text-warn" role="alert">
          <p className="font-medium">{tr("Confirmation requise")}</p>
          <ul className="list-disc space-y-1 pl-5">{risk.map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
      )}
      {err && <Notice kind="error">{err}</Notice>}
      <Button variant={risk ? "danger" : "primary"} onClick={() => save(!!risk)} disabled={busy || !patch || !valid}>{busy ? "…" : risk ? tr("Confirmer et enregistrer") : tr("Enregistrer")}</Button>
    </div>
  );
}
