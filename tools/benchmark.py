"""Reproducible synthetic-only benchmark; emits no account or host identity."""
import ctypes
import json
import os
import platform
import statistics
import time
from pathlib import Path
from app.core import Store
from tests.test_search import populate

def hardware():
    result={'os':platform.platform(),'python':platform.python_version(),'logical_processors':os.cpu_count(),'processor':platform.processor()}
    if os.name=='nt':
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
            result['processor']=winreg.QueryValueEx(key,'ProcessorNameString')[0].strip()
        class Memory(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(n,ctypes.c_ulonglong) for n in ['total','available','pagefile','available_pagefile','virtual','available_virtual','extended']]
        mem=Memory();mem.length=ctypes.sizeof(mem);ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem));result['ram_gib']=round(mem.total/1024**3,1)
    return result

def main():
    path=Path('.tmp')/f'benchmark-{time.time_ns()}.sqlite';store=Store(path)
    begin=time.perf_counter();populate(store);insert=time.perf_counter()-begin
    cases={'first_page':{},'chinese_note_search':{'query':'中文备注'},'tag_filter':{'tag':'科研','exact_tag':True},'sorted_size_page':{'order':'size','descending':False},'last_page':{'offset':49800}}
    results={}
    for name,filters in cases.items():
        times=[]
        for i in range(7):
            begin=time.perf_counter();page=store.search_page(**filters);times.append((time.perf_counter()-begin)*1000)
        results[name]={'median_ms':round(statistics.median(times),3),'max_ms':round(max(times),3),'returned':len(page.rows),'matched':page.total}
    report={'dataset':'50000 synthetic rows; no real WeChat data','hardware':hardware(),'insert_seconds':round(insert,3),'page_size':200,'repetitions':7,'results':results}
    Path('docs/性能测试.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
