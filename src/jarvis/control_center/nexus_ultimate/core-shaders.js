// Both backends use identical projection, additive emissive fields, and materials.
export const glVertex = `#version 300 es
precision highp float;
layout(location=0) in vec3 position;
layout(location=1) in vec3 color;
layout(location=2) in vec3 shape;
uniform vec4 scene; // target width, height, rotation clock, device pixel ratio
uniform vec4 pose;  // yaw, pitch, pulse, state mix
uniform vec4 tint, detail;
out vec2 localUV;
out vec3 ink;
flat out float material;
uniform bool sprites;
const vec2 corners[4] = vec2[4](vec2(-1,-1),vec2(1,-1),vec2(-1,1),vec2(1,1));
void main(){
  vec3 p=position; material=shape.y; float g=shape.z;
  float yaw=pose.x + (g==0. ? scene.z*0.23 : 0.);
  float pitch=pose.y;
  if(g==0.){
    p+=0.009*sin(scene.z*3.2+position.yzx*6.)*sin(position.zxy*4.);
  }
  if(g==-2.){ yaw-=scene.z*0.51; pitch+=0.12*sin(scene.z*0.7); }
  if(g==-3.){ yaw+=scene.z*0.095; p*=1.+0.035*tint.w; }
  if(g==-4.){ yaw-=scene.z*0.14; pitch+=0.07*sin(scene.z); }
  yaw+=pose.x*p.z*0.34; pitch+=pose.y*p.z*0.32;
  if(g>0.){
    const vec3 axes[4]=vec3[4](vec3(-0.247533,-0.930499,0.270000),vec3(-0.245239,-0.921877,0.300000),vec3(0.386840,-0.761548,0.520000),vec3(-0.682477,-0.611740,0.400000));
    vec3 axis=axes[int(g)-1];
    float orbit=scene.z*(0.29+0.12*g)*(g==2.||g==3.?-1.:1.);
    p=p*cos(orbit)+cross(axis,p)*sin(orbit);
    yaw+=sin(scene.z*(0.1+g*0.025)+g)*0.075;
    pitch+=sin(scene.z*0.18+g)*0.055;
    float roll=sin(scene.z*(0.10+g*0.05))*0.08;
    p.xy=mat2(cos(roll),sin(roll),-sin(roll),cos(roll))*p.xy;
  }
  p.xz=mat2(cos(yaw),-sin(yaw),sin(yaw),cos(yaw))*p.xz;
  p.yz=mat2(cos(pitch),sin(pitch),-sin(pitch),cos(pitch))*p.yz;
  float k=min(scene.x,scene.y)*0.318*4.25/(4.25-0.26*p.z);
  vec2 uv=sprites ? vec2(0.) : corners[gl_VertexID];
  localUV=uv;
  float size=max(shape.x*k*(g==-1.?1.:detail.x),0.72*scene.w);
  gl_PointSize=2.*size*pose.z;
  vec2 pixel=(p.xy*k+uv*size)*pose.z;
  gl_Position=vec4(2.*pixel/scene.xy,0.,1.);
  float depth=g==-1.?1.:0.19+0.81*smoothstep(-0.68,0.84,p.z);
  float amount=g==-1.?1.:min(1.,shape.x*k/(0.72*scene.w));
  float flow=g==0.?0.9+0.1*cos(position.y*9.+position.z*5.-scene.z*6.):1.;
  if(g==-4.) flow=0.70+0.68*pow(0.5+0.5*cos(position.x*9.-scene.z*5.+position.y*4.),6.);
  if(g==-1. && material==1.) flow=1.+0.16*sin(scene.z*2.);
  if(detail.y==1.) flow*=0.94+0.14*cos(p.y*4.-detail.z*2.);
  if(detail.y==3. && g<=0.) flow*=0.92+0.15*sin(detail.z*4.+p.z)*cos(detail.z*1.4);
  if(detail.y==4. && g>0.) flow*=0.9+0.32*pow(0.5+0.5*cos(p.x*5.+p.z-detail.z*3.),4.);
  if(detail.y==6.) flow*=0.92+0.12*cos(detail.z*2.1);
  flow*=1.+0.13*tint.w;
  ink=mix(color, tint.rgb*max(color.b,max(color.r,color.g)),pose.w)*depth*amount*flow;
}`;
export const glFragment = `#version 300 es
precision highp float;
in vec2 localUV; in vec3 ink; flat in float material;
uniform vec4 pose; uniform vec4 tint; uniform bool sprites;
out vec4 fragment;
void main(){
  vec2 uv=sprites ? vec2(2.*gl_PointCoord.x-1.,1.-2.*gl_PointCoord.y) : localUV;
  float r2=dot(uv,uv); if(r2>1.) discard;
  vec3 light;
  if(material==2.){
    float z=sqrt(max(0.,1.-r2));
    float lobe=0.5+0.5*sin(uv.y*7.+uv.x*5.+2.*sin(uv.x*3.-uv.y*2.));
    float rim=exp(-8.*z);
    vec3 base=mix(vec3(0.07,0.04,0.22),vec3(0.20,0.05,0.42),lobe)*(0.50+0.35*z);
    base+=vec3(0.38,0.25,0.86)*rim+vec3(0.05,0.06,0.2)*pow(1.-z,2.);
    light=mix(base,tint.rgb*max(base.b,0.05),pose.w)*smoothstep(0.,0.06,z);
  } else if(material==1.){
    float r=sqrt(r2);
    float crossRay=exp(-abs(uv.x)*36.)*exp(-abs(uv.y)*3.8)+exp(-abs(uv.y)*42.)*exp(-abs(uv.x)*3.);
    light=ink*(exp(-r2*34.)+0.50*crossRay+0.15*exp(-r*5.))*(1.-smoothstep(0.84,1.,r));
  } else {
    float glow=exp(-r2*(material==3.?5.8:2.8))*(1.-smoothstep(0.66,1.,r2));
    light=ink*glow;
  }
  fragment=vec4(light,max(light.r,max(light.g,light.b)));
}`;

export const wgsl = `
struct Uniforms { scene:vec4f, pose:vec4f, tint:vec4f, detail:vec4f };
@group(0) @binding(0) var<uniform> u:Uniforms;
struct Out {
 @builtin(position) position:vec4f, @location(0) uv:vec2f,
 @location(1) ink:vec3f, @location(2) @interpolate(flat) material:f32
};
@vertex fn vert(@builtin(vertex_index) vertex:u32,@location(0) xyz:vec3f,@location(1) color:vec3f,@location(2) shape:vec3f)->Out{
 let corners=array<vec2f,4>(vec2f(-1,-1),vec2f(1,-1),vec2f(-1,1),vec2f(1,1));
 let g=shape.z;
 var p=xyz; var yaw=u.pose.x; var pitch=u.pose.y;
 if(g==0.){
   yaw+=u.scene.z*0.23;
   p+=0.009*sin(vec3f(u.scene.z*3.2)+xyz.yzx*6.)*sin(xyz.zxy*4.);
 }
 if(g==-2.){ yaw-=u.scene.z*0.51; pitch+=0.12*sin(u.scene.z*0.7); }
 if(g==-3.){ yaw+=u.scene.z*0.095; p*=1.+0.035*u.tint.w; }
 if(g==-4.){ yaw-=u.scene.z*0.14; pitch+=0.07*sin(u.scene.z); }
 yaw+=u.pose.x*p.z*0.34; pitch+=u.pose.y*p.z*0.32;
 if(g>0.){
   let axes=array<vec3f,4>(vec3f(-0.247533,-0.930499,0.270000),vec3f(-0.245239,-0.921877,0.300000),vec3f(0.386840,-0.761548,0.520000),vec3f(-0.682477,-0.611740,0.400000));
   let axis=axes[u32(g)-1u];
   let orbit=u.scene.z*(0.29+0.12*g)*select(1.,-1.,g==2.||g==3.);
   p=p*cos(orbit)+cross(axis,p)*sin(orbit);
   yaw+=sin(u.scene.z*(0.1+g*0.025)+g)*0.075;
   pitch+=sin(u.scene.z*0.18+g)*0.055;
   let roll=sin(u.scene.z*(0.10+g*0.05))*0.08;
   p=vec3f(p.x*cos(roll)-p.y*sin(roll),p.x*sin(roll)+p.y*cos(roll),p.z);
 }
 p=vec3f(p.x*cos(yaw)+p.z*sin(yaw),p.y,-p.x*sin(yaw)+p.z*cos(yaw));
 p=vec3f(p.x,p.y*cos(pitch)-p.z*sin(pitch),p.y*sin(pitch)+p.z*cos(pitch));
 let k=min(u.scene.x,u.scene.y)*0.318*4.25/(4.25-0.26*p.z);
 var out:Out; out.uv=corners[vertex]; out.material=shape.y;
 let size=max(shape.x*k*select(u.detail.x,1.,g==-1.),0.72*u.scene.w);
 let pix=(p.xy*k+out.uv*size)*u.pose.z;
 out.position=vec4f(2.*pix/u.scene.xy,0.,1.);
 let depth=select(0.19+0.81*smoothstep(-0.68,0.84,p.z),1.,g==-1.);
 let amount=select(min(1.,shape.x*k/(0.72*u.scene.w)),1.,g==-1.);
 var flow=select(1.,0.9+0.1*cos(xyz.y*9.+xyz.z*5.-u.scene.z*6.),g==0.);
 if(g==-4.){ flow=0.70+0.68*pow(0.5+0.5*cos(xyz.x*9.-u.scene.z*5.+xyz.y*4.),6.); }
 if(g==-1. && shape.y==1.){ flow=1.+0.16*sin(u.scene.z*2.); }
 if(u.detail.y==1.){flow*=0.94+0.14*cos(p.y*4.-u.detail.z*2.);}
 if(u.detail.y==3. && g<=0.){flow*=0.92+0.15*sin(u.detail.z*4.+p.z)*cos(u.detail.z*1.4);}
 if(u.detail.y==4. && g>0.){flow*=0.9+0.32*pow(0.5+0.5*cos(p.x*5.+p.z-u.detail.z*3.),4.);}
 if(u.detail.y==6.){flow*=0.92+0.12*cos(u.detail.z*2.1);}
 flow*=1.+0.13*u.tint.w;
 out.ink=mix(color,u.tint.rgb*max(color.b,max(color.r,color.g)),u.pose.w)*depth*amount*flow;
 return out;
}
@fragment fn frag(in:Out)->@location(0) vec4f{
 let r2=dot(in.uv,in.uv); if(r2>1.){discard;}
 var light:vec3f;
 if(in.material==2.){
   let z=sqrt(max(0.,1.-r2));
   let lobe=0.5+0.5*sin(in.uv.y*7.+in.uv.x*5.+2.*sin(in.uv.x*3.-in.uv.y*2.));
   let rim=exp(-8.*z);
   var base=mix(vec3f(0.07,0.04,0.22),vec3f(0.20,0.05,0.42),lobe)*(0.50+0.35*z);
   base+=vec3f(0.38,0.25,0.86)*rim+vec3f(0.05,0.06,0.2)*pow(1.-z,2.);
   light=mix(base,u.tint.rgb*max(base.b,0.05),u.pose.w)*smoothstep(0.,0.06,z);
 } else if(in.material==1.){
   let r=sqrt(r2);
   let ray=exp(-abs(in.uv.x)*36.)*exp(-abs(in.uv.y)*3.8)+exp(-abs(in.uv.y)*42.)*exp(-abs(in.uv.x)*3.);
   light=in.ink*(exp(-r2*34.)+0.5*ray+0.15*exp(-r*5.))*(1.-smoothstep(0.84,1.,r));
 } else {
   let glow=exp(-r2*select(2.8,5.8,in.material==3.))*(1.-smoothstep(0.66,1.,r2));
   light=in.ink*glow;
 }
 return vec4f(light,max(light.r,max(light.g,light.b)));
}`;
