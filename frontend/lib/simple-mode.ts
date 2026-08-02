'use client';
import { useEffect, useState } from 'react';

export function applySimpleMode(enabled:boolean) {
  document.documentElement.dataset.simpleMode=enabled ? 'true' : 'false';
  localStorage.setItem('pfos_simple_mode',String(enabled));
  window.dispatchEvent(new Event('pfos-simple-mode-change'));
}

export function useSimpleMode() {
  const [enabled,setEnabled]=useState(false);
  useEffect(()=>{ const refresh=()=>setEnabled(localStorage.getItem('pfos_simple_mode')==='true'); refresh(); window.addEventListener('pfos-simple-mode-change',refresh); return()=>window.removeEventListener('pfos-simple-mode-change',refresh); },[]);
  return enabled;
}
