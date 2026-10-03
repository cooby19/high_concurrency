use axum::{body::{Body,to_bytes}, extract::{Request,State}, response::{IntoResponse,Response}, routing::any, Router, Json};
use serde_json::{json,Value};
use std::{sync::Arc,time::Duration};
use tokio::sync::Semaphore;
#[derive(Clone)]
struct App {client:reqwest::Client, downstream:String, cpu:Arc<Semaphore>}
fn error(code:u16, message:&str)->Response {(axum::http::StatusCode::from_u16(code).unwrap(),Json(json!({"error":message}))).into_response()}
fn integer(v:&Value,lo:f64,hi:f64)->bool {v.as_f64().is_some_and(|n| n>=lo && n<=hi && n.trunc()==n)}
fn keys(v:&Value,names:&[&str])->bool {v.as_object().is_some_and(|m| m.len()==names.len() && names.iter().all(|k|m.contains_key(*k)))}
async fn handle(State(app):State<App>,req:Request)->Response {
 let path=req.uri().path().to_owned();
 let method=match path.as_str(){"/health"|"/io"=>"GET","/json"|"/cpu"=>"POST",_=>return error(404,"not_found")};
 if req.method().as_str()!=method {return error(405,"method_not_allowed")};
 if req.uri().query().is_some_and(|q|!q.is_empty()) {return error(400,"invalid_request")};
 if path=="/health" {return Json(json!({"status":"ok"})).into_response()}
 if path=="/io" {
  let result=async {
   let response=app.client.get(&app.downstream).header("Accept-Encoding","identity").send().await.ok()?;
   if response.status()!=200 {return None};
   let data=response.bytes().await.ok()?;
   if data.as_ref()!=vec![b'x';1024] {return None};
   Some(([("Content-Type","application/octet-stream")],Body::from(data)).into_response())
  };
  return tokio::time::timeout(Duration::from_millis(1500),result).await.ok().flatten().unwrap_or_else(||error(502,"downstream_error"));
 }
 if !req.headers().get("content-type").and_then(|v|v.to_str().ok()).unwrap_or("").split(';').next().unwrap_or("").trim().eq_ignore_ascii_case("application/json") {return error(415,"unsupported_media_type")};
 let body=match to_bytes(req.into_body(),4096).await {Ok(b)=>b,Err(_)=>return error(413,"payload_too_large")};
 let data:Value=match serde_json::from_slice(&body) {Ok(v)=>v,Err(_)=>return error(400,"invalid_request")};
 if path=="/cpu" {
  if !keys(&data,&["seed"]) || !integer(&data["seed"],0.,4294967295.) {return error(400,"invalid_request")};
  let mut x=data["seed"].as_f64().unwrap() as u32;
  let permit=app.cpu.clone().acquire_owned().await.unwrap();
  let x=tokio::task::spawn_blocking(move || {let _permit=permit;for _ in 0..100000 {x=x.wrapping_mul(1664525).wrapping_add(1013904223);} x}).await.unwrap();
  return Json(json!({"result":x})).into_response()
 }
 if !keys(&data,&["id","name","values","padding"]) || !integer(&data["id"],0.,4294967295.) || !data["name"].as_str().is_some_and(|n|!n.is_empty() && n.len()<=32 && n.bytes().all(|b|b.is_ascii_alphanumeric()||b==b'_')) || data["padding"].as_str()!=Some(&"x".repeat(896)) || !data["values"].as_array().is_some_and(|v|v.len()==16 && v.iter().all(|n|integer(n,-1000.,1000.))) {return error(400,"invalid_request")};
 let sum:i32=data["values"].as_array().unwrap().iter().map(|v|v.as_f64().unwrap() as i32).sum();
 Json(json!({"id":data["id"],"name":data["name"],"sum":sum,"padding":data["padding"]})).into_response()
}
#[tokio::main]
async fn main(){
 let workers=std::env::var("WORKERS").unwrap_or("1".into()).parse().unwrap();
 let app=App {client:reqwest::Client::builder().http1_only().retry(reqwest::retry::never()).no_proxy().redirect(reqwest::redirect::Policy::none()).timeout(Duration::from_millis(1500)).build().unwrap(),downstream:std::env::var("DOWNSTREAM_URL").unwrap(),cpu:Arc::new(Semaphore::new(workers))};
 let router=Router::new().fallback(any(handle)).with_state(app);
 let port=std::env::var("PORT").unwrap_or("8080".into());
 let listener=tokio::net::TcpListener::bind(format!("0.0.0.0:{port}")).await.unwrap();
 axum::serve(listener,router).await.unwrap();
}
