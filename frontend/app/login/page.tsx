'use client';
import {useEffect, useState} from 'react';
import {useRouter} from 'next/navigation';
import {api} from '@/lib/api';

export default function Login() {
  const [email,setEmail]=useState(''), [password,setPassword]=useState('');
  const [name,setName]=useState(''), [confirm,setConfirm]=useState('');
  const [error,setError]=useState(''), [register,setRegister]=useState(false);
  const [desktop,setDesktop]=useState(false), [firstLaunch,setFirstLaunch]=useState(false);
  const [checking,setChecking]=useState(true), [checkFailed,setCheckFailed]=useState(false);
  const [busy,setBusy]=useState(false);
  const router=useRouter();
  async function checkSetup() {
    setChecking(true); setCheckFailed(false); setError('');
    const local=Boolean((window as Window & {pfosDesktop?: unknown}).pfosDesktop);
    setDesktop(local);
    try {
      if (local) {
        const status=await api('/desktop/setup');
        setFirstLaunch(status.setup_required); setRegister(status.setup_required);
      }
    } catch {
      setCheckFailed(true); setError('PFOS could not check your local household. Retry to continue.');
    } finally { setChecking(false); }
  }
  useEffect(()=>{void checkSetup()},[]);
  async function submit(e:React.FormEvent) {
    e.preventDefault();
    if (busy || checking || checkFailed) return;
    setError('');
    if (register && password!==confirm) {setError('Passwords do not match.'); return;}
    if (register && (password.length<10 || !/[a-zA-Z]/.test(password) || !/[0-9]/.test(password))) {
      setError('Use at least 10 characters, including a letter and a number.'); return;
    }
    setBusy(true);
    try {
      const r=await api('/auth/'+(register?'register':'login'),{method:'POST',body:JSON.stringify(
        register?{email,password,display_name:name.trim() || email.split('@')[0]}:{email,password})});
      localStorage.setItem('pfos_token',r.access_token);
      localStorage.removeItem('pfos_view_user_id');
      router.replace('/dashboard');
    } catch(e) {setError(e instanceof Error?e.message:'Unable to sign in'); setBusy(false);}
  }
  return <main className="grid min-h-screen place-items-center bg-navy p-5">
    <form onSubmit={submit} className="w-full max-w-md rounded-2xl bg-white p-7 shadow-xl">
      <h1 className="text-3xl font-bold">PF<span className="text-emerald-500">OS</span></h1>
      <h2 className="mt-4 text-xl font-semibold">{firstLaunch?'Welcome to PFOS':register?'Create your household':'Welcome back'}</h2>
      <p className="mb-5 mt-2 text-sm text-slate-600">{desktop
        ? firstLaunch?'Set up your private household on this computer. Your accounts, transactions, and settings are saved locally.':'Sign in to your household saved on this computer.'
        :'Your private household money system.'}</p>
      {firstLaunch && <p className="mb-5 rounded-lg bg-slate-50 p-3 text-sm text-slate-600">Your email identifies your local account; no email verification is needed. Use File → Show Data Folder to find your saved data. Existing server data is not imported automatically.</p>}
      {error && <p role="alert" className="mb-3 rounded bg-red-50 p-2 text-sm text-red-700">{error}</p>}
      {checking?<p role="status">Checking your household…</p>:checkFailed?
        <button type="button" onClick={()=>void checkSetup()} className="w-full rounded-lg bg-navy py-2.5 text-white">Retry</button>:
        <><fieldset disabled={busy}>
          {register && <><label htmlFor="name" className="label">Your name</label><input id="name" autoComplete="name" className="mb-4 mt-1 w-full rounded-lg border p-2" value={name} onChange={e=>setName(e.target.value)} required/></>}
          <label htmlFor="email" className="label">Email</label><input id="email" autoComplete="username" className="mb-4 mt-1 w-full rounded-lg border p-2" value={email} onChange={e=>setEmail(e.target.value)} type="email" required/>
          <label htmlFor="password" className="label">Password</label><input id="password" autoComplete={register?'new-password':'current-password'} className="mb-3 mt-1 w-full rounded-lg border p-2" value={password} onChange={e=>setPassword(e.target.value)} type="password" required/>
          {register && <><p className="mb-3 text-xs text-slate-500">Use at least 10 characters, including a letter and a number.</p><label htmlFor="confirm" className="label">Confirm password</label><input id="confirm" autoComplete="new-password" className="mb-5 mt-1 w-full rounded-lg border p-2" value={confirm} onChange={e=>setConfirm(e.target.value)} type="password" required/></>}
          <button className="mt-2 w-full rounded-lg bg-navy py-2.5 font-medium text-white disabled:opacity-50">{busy?'Please wait…':register?'Create private household':'Sign in'}</button>
          {!firstLaunch && <button type="button" onClick={()=>{setRegister(!register);setError('');setPassword('');setConfirm('')}} className="mt-4 w-full text-sm text-slate-600">{register?'Already have an account? Sign in':'New here? Create an account'}</button>}
        </fieldset></>}
    </form>
  </main>;
}
