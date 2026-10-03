package main

import (
 "bytes"
 "encoding/json"
 "io"
 "math"
 "net/http"
 "os"
 "regexp"
 "strings"
 "time"
 "unicode/utf8"
)
var names = regexp.MustCompile(`^[A-Za-z0-9_]{1,32}$`)
var client = &http.Client{Timeout:1500*time.Millisecond, CheckRedirect:func(r *http.Request, via []*http.Request) error {return http.ErrUseLastResponse}, Transport:&http.Transport{DisableCompression:true, MaxIdleConns:100000, MaxIdleConnsPerHost:100000}}
func output(w http.ResponseWriter, code int, data any) {w.Header().Set("Content-Type","application/json"); w.WriteHeader(code); json.NewEncoder(w).Encode(data)}
func fail(w http.ResponseWriter, code int, message string) {output(w,code,map[string]string{"error":message})}
func integer(v any, lo, hi float64) bool {n,ok:=v.(float64); return ok && n>=lo && n<=hi && math.Trunc(n)==n}
func handler(w http.ResponseWriter,r *http.Request) {
 path:=strings.SplitN(r.RequestURI,"?",2)[0]
 method,ok:=map[string]string{"/health":"GET","/io":"GET","/json":"POST","/cpu":"POST"}[path]
 if !ok {fail(w,404,"not_found");return}; if r.Method!=method {fail(w,405,"method_not_allowed");return}; if r.URL.RawQuery!="" {fail(w,400,"invalid_request");return}
 if path=="/health" {output(w,200,map[string]string{"status":"ok"});return}
 if path=="/io" {
  // A fresh request with a non-replayable body prevents Transport retrying on stale connections.
  req,err:=http.NewRequest("GET",os.Getenv("DOWNSTREAM_URL"),io.NopCloser(strings.NewReader("")))
  if err!=nil {fail(w,502,"downstream_error");return}; req.Header.Set("Accept-Encoding","identity")
  resp,err:=client.Do(req); if err!=nil {fail(w,502,"downstream_error");return}; defer resp.Body.Close()
  body,err:=io.ReadAll(io.LimitReader(resp.Body,1025)); if err!=nil || resp.StatusCode!=200 || !bytes.Equal(body,bytes.Repeat([]byte("x"),1024)) {fail(w,502,"downstream_error");return}
  w.Header().Set("Content-Type","application/octet-stream");w.Write(body);return
 }
 if strings.ToLower(strings.TrimSpace(strings.SplitN(r.Header.Get("Content-Type"),";",2)[0]))!="application/json" {fail(w,415,"unsupported_media_type");return}
 body,err:=io.ReadAll(io.LimitReader(r.Body,4097)); if len(body)>4096 {fail(w,413,"payload_too_large");return}
 var data map[string]any
 if err!=nil || !utf8.Valid(body) || json.Unmarshal(body,&data)!=nil || data==nil {fail(w,400,"invalid_request");return}
 if path=="/cpu" {
  if len(data)!=1 || !integer(data["seed"],0,4294967295) {fail(w,400,"invalid_request");return}
  x:=uint32(data["seed"].(float64));for i:=0;i<100000;i++ {x=1664525*x+1013904223};output(w,200,map[string]uint32{"result":x});return
 }
 name,ok:=data["name"].(string);values,vok:=data["values"].([]any);padding,pok:=data["padding"].(string)
 if len(data)!=4 || !integer(data["id"],0,4294967295) || !ok || !names.MatchString(name) || !vok || len(values)!=16 || !pok || padding!=strings.Repeat("x",896) {fail(w,400,"invalid_request");return}
 sum:=0;for _,v:=range values {if !integer(v,-1000,1000) {fail(w,400,"invalid_request");return};sum+=int(v.(float64))}
 output(w,200,map[string]any{"id":data["id"],"name":name,"sum":sum,"padding":padding})
}
func main() {port:=os.Getenv("PORT");if port=="" {port="8080"};server:=http.Server{Addr:":"+port,Handler:http.HandlerFunc(handler),ReadHeaderTimeout:2*time.Second};if err:=server.ListenAndServe();err!=nil {panic(err)}}
