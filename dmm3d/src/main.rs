use std::{collections::{BTreeMap,HashMap},env,error::Error,fs,path::Path};

#[derive(Debug,Clone)]
struct Atom { path:String, vars:String }
#[derive(Debug,Clone)]
struct Cell { x:i32,y:i32,z:i32,atoms:Vec<Atom> }
#[derive(Debug)]
struct Map { cells:Vec<Cell>, definitions:usize }

fn quoted(s:&str)->Option<(String,usize)> {
    if !s.starts_with('"') {return None}
    let mut escape=false;
    for (i,c) in s.char_indices().skip(1) {
        if escape {escape=false;continue}
        if c=='\\' {escape=true;continue}
        if c=='"' {return Some((s[1..i].to_owned(),i+1))}
    }
    None
}
fn matching(s:&str,open:char,close:char)->Option<usize>{
    let mut depth=0;let mut quote=false;let mut escape=false;
    for (i,c) in s.char_indices(){
        if escape {escape=false;continue}
        if quote && c=='\\'{escape=true;continue}
        if c=='"'{quote=!quote;continue}
        if quote{continue}
        if c==open{depth+=1}else if c==close{depth-=1;if depth==0{return Some(i)}}
    }
    None
}
fn split_atoms(s:&str)->Vec<Atom>{
    let mut out=Vec::new();let mut start=0;let mut braces=0;let mut quote=false;let mut escape=false;
    for (i,c) in s.char_indices().chain(std::iter::once((s.len(),','))){
        if escape{escape=false;continue}
        if quote&&c=='\\'{escape=true;continue}
        if c=='"'{quote=!quote;continue}
        if quote{continue}
        if c=='{'{braces+=1}else if c=='}'{braces-=1}
        if c==','&&braces==0{
            let raw=s[start..i].trim();
            if !raw.is_empty(){let (path,vars)=raw.split_once('{').map(|(p,v)|(p.trim(),v.trim_end_matches('}').trim())).unwrap_or((raw,""));out.push(Atom{path:path.to_string(),vars:vars.to_string()});}
            start=i+1;
        }
    }
    out
}
fn parse(input:&str)->Result<Map,Box<dyn Error>>{
    let mut defs:HashMap<String,Vec<Atom>>=HashMap::new();let mut cells=Vec::new();let mut pos=0;
    while pos<input.len(){
        let rest=&input[pos..];let line=rest.trim_start_matches(char::is_whitespace);pos+=rest.len()-line.len();
        if line.is_empty(){break}
        if line.starts_with('"'){
            if let Some((key,end))=quoted(line){let after=line[end..].trim_start();if after.starts_with('='){
                let rhs=after[1..].trim_start();if rhs.starts_with('('){
                    let end_paren=matching(rhs,'(',')').ok_or("unclosed definition")?;
                    defs.insert(key,split_atoms(&rhs[1..end_paren]));
                    pos+=line.len()-rhs.len()+end_paren+1;continue;
                }
            }}
        }
        if line.starts_with('('){
            if let Some(end)=matching(line,'(',')'){
                let coords=&line[1..end];let nums:Vec<i32>=coords.split(',').map(|v|v.trim().parse::<i32>()).collect::<Result<_,_>>()?;
                if nums.len()==3{
                    let rhs=line[end+1..].trim_start();
                    if rhs.starts_with('='){
                        let rhs=rhs[1..].trim_start();
                        if let Some((grid,n))=quoted(rhs){
                            let width=defs.keys().next().ok_or("grid without definitions")?.len();
                            if width==0{return Err("empty dictionary key".into())}
                            // DMM coordinate blocks are column-major: each line is a row, X increases across characters.
                            for (row,raw) in grid.lines().filter(|r|!r.trim().is_empty()).enumerate(){
                                let line=raw.trim_end_matches('\r');
                                if !line.is_ascii(){return Err("non-ASCII grid keys unsupported".into())}
                                if line.len()%width!=0{return Err(format!("grid row length {} not divisible by key width {}",line.len(),width).into())}
                                for (col,key) in line.as_bytes().chunks(width).enumerate(){
                                    let key=std::str::from_utf8(key)?;
                                    let atoms=defs.get(key).ok_or_else(||format!("undefined tile key: {key}"))?.clone();
                                    cells.push(Cell{x:nums[0]+col as i32,y:nums[1]+row as i32,z:nums[2],atoms});
                                }
                            }
                            pos+=line.len()-rhs.len()+n;continue;
                        }
                    }
                }
            }
        }
        pos+=line.find('\n').map(|n|n+1).unwrap_or(line.len());
    }
    Ok(Map{cells,definitions:defs.len()})
}
#[derive(Clone,Copy,PartialEq,Eq)]
enum Kind{Floor,Wall,Door,Window,Table,Machine,Other}
impl Kind{fn label(self)->&'static str{match self{Self::Floor=>"floor",Self::Wall=>"wall",Self::Door=>"door",Self::Window=>"window",Self::Table=>"table",Self::Machine=>"machine",Self::Other=>"other"}}}
fn classify(path:&str,rules:&[(String,Kind)])->Kind{
    for (prefix,kind) in rules {if path.starts_with(prefix){return *kind}}
    let p=path.to_ascii_lowercase();
    if p.contains("/window"){Kind::Window}
    else if p.contains("/door")||p.contains("/airlock"){Kind::Door}
    else if p.contains("/wall")||p.contains("/closed/"){Kind::Wall}
    else if p.contains("/table"){Kind::Table}
    else if p.starts_with("/obj/machinery/"){Kind::Machine}
    else if p.starts_with("/turf/"){Kind::Floor}
    else{Kind::Other}
}
fn rules_file(path:Option<&str>)->Result<Vec<(String,Kind)>,Box<dyn Error>>{
    let Some(path)=path else{return Ok(Vec::new())};let mut rules=Vec::new();
    for (n,line) in fs::read_to_string(path)?.lines().enumerate(){
        let line=line.trim();if line.is_empty()||line.starts_with('#'){continue}
        let (prefix,kind)=line.split_once('=').ok_or_else(||format!("rule line {} missing =",n+1))?;
        let kind=match kind.trim(){"floor"=>Kind::Floor,"wall"=>Kind::Wall,"door"=>Kind::Door,"window"=>Kind::Window,"table"=>Kind::Table,"machine"=>Kind::Machine,"ignore"=>Kind::Other,x=>return Err(format!("unknown kind {x}").into())};
        rules.push((prefix.trim().to_owned(),kind));
    }
    rules.sort_by_key(|(s,_)|std::cmp::Reverse(s.len()));Ok(rules)
}
struct Mesh{vertices:Vec<[f32;3]>,faces:Vec<([usize;4],Kind)>}
impl Mesh{
 fn new()->Self{Self{vertices:Vec::new(),faces:Vec::new()}}
 fn quad(&mut self,a:[f32;3],b:[f32;3],c:[f32;3],d:[f32;3],kind:Kind){let i=self.vertices.len()+1;self.vertices.extend([a,b,c,d]);self.faces.push(([i,i+1,i+2,i+3],kind));}
 fn cube(&mut self,x:f32,y:f32,z:f32,w:f32,d:f32,h:f32,kind:Kind,sides:[bool;4]){
  let (x2,y2,z2)=(x+w,y+h,z+d);
  self.quad([x,y,z],[x2,y,z],[x2,y,z2],[x,y,z2],kind);
  self.quad([x,y2,z2],[x2,y2,z2],[x2,y2,z],[x,y2,z],kind);
  if sides[0]{self.quad([x,y,z],[x,y2,z],[x2,y2,z],[x2,y,z],kind)}
  if sides[1]{self.quad([x2,y,z2],[x2,y2,z2],[x,y2,z2],[x,y,z2],kind)}
  if sides[2]{self.quad([x,y,z2],[x,y2,z2],[x,y2,z],[x,y,z],kind)}
  if sides[3]{self.quad([x2,y,z],[x2,y2,z],[x2,y2,z2],[x2,y,z2],kind)}
 }
 fn write(&self,path:&Path)->Result<(),Box<dyn Error>>{
  let mut s=String::from("# DMM3D generated geometry\nmtllib station.mtl\n");
  for v in &self.vertices{s.push_str(&format!("v {} {} {}\n",v[0],v[1],v[2]));}
  let mut last="";
  for (f,kind) in &self.faces{let k=kind.label();if last!=k{s.push_str(&format!("usemtl {k}\n"));last=k} s.push_str(&format!("f {} {} {} {}\n",f[0],f[1],f[2],f[3]));}
  fs::write(path,s)?;Ok(())
 }
}
fn escape_json(s:&str)->String{let mut out=String::from("\"");for c in s.chars(){match c{'"'=>out.push_str("\\\""),'\\'=>out.push_str("\\\\"),'\n'=>out.push_str("\\n"),'\r'=>out.push_str("\\r"),'\t'=>out.push_str("\\t"),c if c.is_control()=>out.push_str(&format!("\\u{:04x}",c as u32)),c=>out.push(c)}}out.push('"');out}
fn run()->Result<(),Box<dyn Error>>{
 let args:Vec<String>=env::args().collect();if args.len()<3{eprintln!("Usage: dmm3d <input.dmm> <output-dir> [--rules rules.txt] [--tile-size 1.0] [--wall-height 2.8]\nOutputs station.obj, station.mtl, scene.json");return Err("missing arguments".into())}
 let mut rules=None;let mut tile=1.0_f32;let mut wall=2.8_f32;let mut i=3;
 while i<args.len(){match args[i].as_str(){"--rules"=>{i+=1;rules=Some(args.get(i).ok_or("missing rules path")?.as_str())},"--tile-size"=>{i+=1;tile=args.get(i).ok_or("missing tile size")?.parse()?},"--wall-height"=>{i+=1;wall=args.get(i).ok_or("missing wall height")?.parse()?},x=>return Err(format!("unknown argument {x}").into())}i+=1}
 if !tile.is_finite()||!wall.is_finite()||tile<=0.0||wall<=0.0{return Err("tile size and wall height must be positive finite numbers".into())}
 let rules=rules_file(rules)?;let map=parse(&fs::read_to_string(&args[1])?)?;if map.cells.is_empty(){return Err("no map cells found".into())}
 let out=Path::new(&args[2]);fs::create_dir_all(out)?;
 let mut occupied=HashMap::new();let mut kinds=Vec::new();
 for c in &map.cells{let mut kind=Kind::Other;for a in &c.atoms{let k=classify(&a.path,&rules);if k==Kind::Wall{kind=k;break}if matches!(k,Kind::Floor)&&kind==Kind::Other{kind=k}}occupied.insert((c.x,c.y,c.z),kind);kinds.push(kind);}
 let mut mesh=Mesh::new();let mut counts=BTreeMap::<String,usize>::new();let mut scene=String::from("{\n  \"format\": \"dmm3d-scene-v1\",\n  \"coordinate_system\": \"x_east_y_up_z_north\",\n  \"cells\": [\n");
 for (index,c) in map.cells.iter().enumerate(){
  let x=c.x as f32*tile;let z=c.y as f32*tile;let y=(c.z-1) as f32*(wall+0.3);
  let kind=kinds[index];
  if kind==Kind::Wall{
   let is_wall=|dx,dy|occupied.get(&(c.x+dx,c.y+dy,c.z))==Some(&Kind::Wall);
   mesh.cube(x,y,z,tile,tile,wall,Kind::Wall,[!is_wall(0,-1),!is_wall(0,1),!is_wall(-1,0),!is_wall(1,0)]);
  }else if kind==Kind::Floor{mesh.cube(x,y-0.12,z,tile,tile,0.12,Kind::Floor,[true;4]);}
  for a in &c.atoms{
   let k=classify(&a.path,&rules);*counts.entry(k.label().to_owned()).or_default()+=1;
   match k{
    Kind::Door=>mesh.cube(x+tile*0.12,y,z+tile*0.4,tile*0.76,tile*0.2,wall*0.9,k,[true;4]),
    Kind::Window=>mesh.cube(x+tile*0.08,y+wall*0.3,z+tile*0.43,tile*0.84,tile*0.14,wall*0.4,k,[true;4]),
    Kind::Table=>mesh.cube(x+tile*0.1,y+wall*0.25,z+tile*0.1,tile*0.8,tile*0.8,tile*0.07,k,[true;4]),
    Kind::Machine=>mesh.cube(x+tile*0.2,y,z+tile*0.2,tile*0.6,tile*0.6,wall*0.55,k,[true;4]),
    _=>{}
   }
  }
  if index>0{scene.push_str(",\n")}
  scene.push_str(&format!("    {{\"x\":{},\"y\":{},\"z\":{},\"atoms\":[",c.x,c.y,c.z));
  for (j,a) in c.atoms.iter().enumerate(){if j>0{scene.push(',')};scene.push_str(&format!("{{\"path\":{},\"vars\":{},\"kind\":{}}}",escape_json(&a.path),escape_json(&a.vars),escape_json(classify(&a.path,&rules).label())))}
  scene.push_str("]}");
 }
 scene.push_str("\n  ]\n}\n");fs::write(out.join("scene.json"),scene)?;
 mesh.write(&out.join("station.obj"))?;
 let materials=[("floor","0.38 0.48 0.53"),("wall","0.58 0.62 0.68"),("door","0.8 0.55 0.20"),("window","0.25 0.70 0.85"),("table","0.4 0.45 0.50"),("machine","0.3 0.65 0.40")];
 let mtl=materials.iter().map(|(name,color)|format!("newmtl {name}\nKd {color}\nKa 0.1 0.1 0.1\nKs 0.1 0.1 0.1\nillum 2\n\n")).collect::<String>();fs::write(out.join("station.mtl"),mtl)?;
 println!("Parsed {} dictionary entries, {} cells, {} faces",map.definitions,map.cells.len(),mesh.faces.len());for (k,v) in counts{println!("  {k}: {v}")};println!("Exported to {}",out.display());Ok(())
}
fn main(){if let Err(e)=run(){eprintln!("Error: {e}");std::process::exit(1)}}
#[cfg(test)]mod tests{use super::*;
 #[test]fn parses_sample(){let m=parse(include_str!("../examples/sample.dmm")).unwrap();assert_eq!(m.cells.len(),20);assert_eq!(m.definitions,5);assert!(m.cells.iter().any(|c|c.atoms.iter().any(|a|a.path.contains("/door"))));}
 #[test]fn handles_atom_vars(){let a=split_atoms("/obj/machinery/door{dir = 4; name = \"A,B\"},/turf/open/floor");assert_eq!(a.len(),2);assert!(a[0].vars.contains("A,B"));}
}
