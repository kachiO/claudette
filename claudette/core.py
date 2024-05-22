# AUTOGENERATED! DO NOT EDIT! File to edit: ../00_core.ipynb.

# %% auto 0
__all__ = ['empty', 'models', 'find_block', 'contents', 'usage', 'mk_msgs', 'Client', 'call_func', 'mk_toolres', 'Chat',
           'img_msg', 'text_msg', 'mk_msg']

# %% ../00_core.ipynb 6
import inspect, typing, mimetypes, base64, json
from collections import abc
try: from IPython import display
except: display=None

from anthropic import Anthropic
from anthropic.types import Usage, TextBlock, Message
from anthropic.types.beta.tools import ToolsBetaMessage, tool_use_block
from anthropic.resources.beta.tools import messages

from toolslm.funccall import *

from fastcore import imghdr
from fastcore.meta import delegates
from fastcore.utils import *

# %% ../00_core.ipynb 8
empty = inspect.Parameter.empty

# %% ../00_core.ipynb 10
models = 'claude-3-opus-20240229','claude-3-sonnet-20240229','claude-3-haiku-20240307'

# %% ../00_core.ipynb 22
def find_block(r:abc.Mapping, # The message to look in
               blk_type:type=TextBlock  # The type of block to find
              ):
    "Find the first block of type `blk_type` in `r.content`."
    return first(o for o in r.content if isinstance(o,blk_type))

# %% ../00_core.ipynb 25
def contents(r):
    "Helper to get the contents from Claude response `r`."
    blk = find_block(r)
    if not blk and r.content: blk = r.content[0]
    return blk.text.strip() if hasattr(blk,'text') else blk

# %% ../00_core.ipynb 28
@patch
def _repr_markdown_(self:(ToolsBetaMessage,Message)):
    det = '\n- '.join(f'{k}: {v}' for k,v in self.model_dump().items())
    return f"""{contents(self)}

<details>

- {det}

</details>"""

# %% ../00_core.ipynb 33
def usage(inp=0, # Number of input tokens
          out=0  # Number of output tokens
         ):
    "Slightly more concise version of `Usage`."
    return Usage(input_tokens=inp, output_tokens=out)

# %% ../00_core.ipynb 36
@patch(as_prop=True)
def total(self:Usage): return self.input_tokens+self.output_tokens

# %% ../00_core.ipynb 39
@patch
def __repr__(self:Usage): return f'In: {self.input_tokens}; Out: {self.output_tokens}; Total: {self.total}'

# %% ../00_core.ipynb 42
@patch
def __add__(self:Usage, b):
    "Add together each of `input_tokens` and `output_tokens`"
    return usage(self.input_tokens+b.input_tokens, self.output_tokens+b.output_tokens)

# %% ../00_core.ipynb 52
def mk_msgs(msgs:list, **kw):
    "Helper to set 'assistant' role on alternate messages."
    if isinstance(msgs,str): msgs=[msgs]
    return [mk_msg(o, ('user','assistant')[i%2], **kw) for i,o in enumerate(msgs)]

# %% ../00_core.ipynb 59
class Client:
    def __init__(self, model, cli=None):
        "Basic Anthropic messages client."
        self.model,self.use = model,Usage(input_tokens=0,output_tokens=0)
        self.c = (cli or Anthropic())

# %% ../00_core.ipynb 62
@patch
def _r(self:Client, r:ToolsBetaMessage, prefill=''):
    "Store the result of the message and accrue total usage."
    if prefill:
        blk = find_block(r)
        blk.text = prefill + (blk.text or '')
    self.result = r
    self.use += r.usage
    return r

# %% ../00_core.ipynb 66
@patch
def _stream(self:Client, msgs:list, prefill='', **kwargs):
    with self.c.messages.stream(model=self.model, messages=mk_msgs(msgs), **kwargs) as s:
        if prefill: yield(prefill)
        yield from s.text_stream
        self._r(s.get_final_message(), prefill)

# %% ../00_core.ipynb 68
@patch
@delegates(messages.Messages.create)
def __call__(self:Client,
             msgs:list, # List of messages in the dialog
             sp='', # The system prompt
             temp=0, # Temperature
             maxtok=4096, # Maximum tokens
             prefill='', # Optional prefill to pass to Claude as start of its response
             stream:bool=False, # Stream response?
             **kwargs):
    "Make a call to Claude."
    pref = [prefill.strip()] if prefill else []
    if not isinstance(msgs,list): msgs = [msgs]
    msgs = mk_msgs(msgs+pref)
    if stream: return self._stream(msgs, prefill=prefill, max_tokens=maxtok, system=sp, temperature=temp, **kwargs)
    res = self.c.beta.tools.messages.create(
        model=self.model, messages=msgs, max_tokens=maxtok, system=sp, temperature=temp, **kwargs)
    self._r(res, prefill)
    return self.result

# %% ../00_core.ipynb 88
def _mk_ns(*funcs:list[callable]) -> dict[str,callable]:
    "Create a `dict` of name to function in `funcs`, to use as a namespace"
    return {f.__name__:f for f in funcs}

# %% ../00_core.ipynb 90
def call_func(fc:tool_use_block.ToolUseBlock, # Tool use block from Claude's message
              ns:Optional[abc.Mapping]=None, # Namespace to search for tools, defaults to `globals()`
              obj:Optional=None # Object to search for tools
             ):
    "Call the function in the tool response `tr`, using namespace `ns`."
    if ns is None: ns=globals()
    if not isinstance(ns, abc.Mapping): ns = _mk_ns(*ns)
    func = getattr(obj, fc.name, None)
    if not func: func = ns[fc.name]
    res = func(**fc.input)
    return dict(type="tool_result", tool_use_id=fc.id, content=str(res))    

# %% ../00_core.ipynb 93
def mk_toolres(
    r:abc.Mapping, # Tool use request response from Claude
    ns:Optional[abc.Mapping]=None, # Namespace to search for tools
    obj:Optional=None # Class to search for tools
    ):
    "Create a `tool_result` message from response `r`."
    cts = getattr(r, 'content', [])
    res = [mk_msg(r)]
    tcs = [call_func(o, ns=ns, obj=obj) for o in cts if isinstance(o,tool_use_block.ToolUseBlock)]
    if tcs: res.append(mk_msg(tcs))
    return res

# %% ../00_core.ipynb 103
class Chat:
    def __init__(self,
                 model:Optional[str]=None, # Model to use (leave empty if passing `cli`)
                 cli:Optional[Client]=None, # Client to use (leave empty if passing `model`)
                 sp='', # Optional system prompt
                 tools:Optional[list]=None): # List of tools to make available to Claude
        "Anthropic chat client."
        assert model or cli
        self.c = (cli or Client(model))
        self.h,self.sp,self.tools = [],sp,tools
    
    @property
    def use(self): return self.c.use

# %% ../00_core.ipynb 106
@patch
def _stream(self:Chat, res):
    yield from res
    self.h += mk_toolres(self.c.result, ns=self.tools, obj=self)

# %% ../00_core.ipynb 107
@patch
def __call__(self:Chat,
             pr=None,  # Prompt / message
             temp=0, # Temperature
             maxtok=4096, # Maximum tokens
             stream=False, # Stream response?
             prefill='', # Optional prefill to pass to Claude as start of its response
             **kw):
    if pr and self.h and self.h[-1].get('role','')=='user':
        self() # There's already a user request pending, so complete it
    if pr: self.h.append(mk_msg(pr))
    if self.tools: kw['tools'] = [get_schema(o) for o in self.tools]
    res = self.c(self.h, stream=stream, prefill=prefill, sp=self.sp, temp=temp, maxtok=maxtok, **kw)
    if stream: return self._stream(res)
    self.h += mk_toolres(self.c.result, ns=self.tools, obj=self)
    return res

# %% ../00_core.ipynb 126
def img_msg(data:bytes)->dict:
    "Convert image `data` into an encoded `dict`"
    img = base64.b64encode(data).decode("utf-8")
    mtype = mimetypes.types_map['.'+imghdr.what(None, h=data)]
    r = dict(type="base64", media_type=mtype, data=img)
    return {"type": "image", "source": r}

# %% ../00_core.ipynb 128
def text_msg(s:str)->dict:
    "Convert `s` to a text message"
    return {"type": "text", "text": s}

# %% ../00_core.ipynb 132
def _mk_content(src):
    "Create appropriate content data structure based on type of content"
    if isinstance(src,str): return text_msg(src)
    if isinstance(src,bytes): return img_msg(src)
    return src

# %% ../00_core.ipynb 135
def mk_msg(content, # A string, list, or dict containing the contents of the message
           role='user', # Must be 'user' or 'assistant'
           **kw):
    "Helper to create a `dict` appropriate for a Claude message. `kw` are added as key/value pairs to the message"
    if hasattr(content, 'content'): content,role = content.content,content.role
    if isinstance(content, abc.Mapping): content=content['content']
    if not isinstance(content, list): content=[content]
    content = [_mk_content(o) for o in content] if content else '.'
    return dict(role=role, content=content, **kw)
