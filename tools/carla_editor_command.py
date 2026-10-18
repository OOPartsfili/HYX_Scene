"""Call this project's local CARLA console RPC (not exposed by the installed wheel).

Protocol follows LibCarla rpc/Client.h and Metadata.h. Limited MessagePack codec
for the simple console/version requests and replies; no extra dependencies.
"""
import socket,struct,sys
def pack(v):
 if v is None:return b'\xc0'
 if isinstance(v,bool):return b'\xc3' if v else b'\xc2'
 if isinstance(v,int) and 0<=v<128:return bytes([v])
 if isinstance(v,str):
  b=v.encode();n=len(b);return (bytes([0xa0+n]) if n<32 else b'\xd9'+bytes([n]) if n<256 else b'\xda'+struct.pack('>H',n))+b
 if isinstance(v,list):return (bytes([0x90+len(v)]) if len(v)<16 else b'\xdc'+struct.pack('>H',len(v)))+b''.join(pack(x) for x in v)
 raise TypeError(type(v))
def recv_exact(s,n):
 b=b''
 while len(b)<n:
  data=s.recv(n-len(b))
  if not data:raise EOFError('RPC connection closed')
  b+=data
 return b
def unpack(s):
 b=recv_exact(s,1)[0]
 if b<128:return b
 if b>=224:return b-256
 if b==192:return None
 if b in (194,195):return b==195
 if 160<=b<=191:return recv_exact(s,b-160).decode()
 if 144<=b<=159:return [unpack(s) for _ in range(b-144)]
 if 128<=b<=143:return {unpack(s):unpack(s) for _ in range(b-128)}
 sizes={204:('>B',1),205:('>H',2),206:('>I',4),207:('>Q',8),208:('>b',1),209:('>h',2),210:('>i',4),211:('>q',8),202:('>f',4),203:('>d',8)}
 if b in sizes:
  fmt,n=sizes[b];return struct.unpack(fmt,recv_exact(s,n))[0]
 if b in (217,218,219,220,221,222,223):
  nbytes={217:1,218:2,219:4,220:2,221:4,222:2,223:4}[b];n=int.from_bytes(recv_exact(s,nbytes),'big')
  if b<=219:return recv_exact(s,n).decode()
  if b<=221:return [unpack(s) for _ in range(n)]
  return {unpack(s):unpack(s) for _ in range(n)}
 raise ValueError('Unsupported MessagePack tag '+str(b))
def call(function,*args,timeout=90):
 with socket.create_connection(('127.0.0.1',2000),timeout=timeout) as s:
  s.sendall(pack([0,1,function,[[False],*args]]));reply=unpack(s)
 if reply[0]!=1 or reply[1]!=1 or reply[2] is not None:raise RuntimeError(reply)
 return reply[3]
if __name__=='__main__':
 print(call('version') if len(sys.argv)==1 else call('console_command',sys.argv[1]))
