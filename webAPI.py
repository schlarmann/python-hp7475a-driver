import argparse
import json
import base64
from io import BytesIO 
from flask import Flask, request, jsonify
from threading import Thread
import os
import queue
import time
import tempfile
import shutil


HP7475_TTY_PORT = "/dev/ttyUSB0"
HP7475_TTY_BAUD = "4800"
HP7475_DO_HIGH_RES = True

STATUS_UPLOADED = 0
STATUS_START_PRINT = 10
STATUS_DONE = 20
STATUS_PRINT_FAILED = -10
STATUS_ALREADY_PRINTING = -20

VPYPE_READ_MULTIPLE_SINGLE_LAYER = "vpype read -m -l 'new' {infile1} read -m -l 'new' {infile2} read -m -l 'new' {infile3} read -m -l 'new' {infile4} read -m -l 'new' {infile5} read -m -l 'new' {infile6} write {outfile}" 

VPYPE_A4_TRANSLATE_PORTRAIT = "translate ' -0.5cm' 0cm"
VPYPE_A4_TRANSLATE_LANDSCAPE = ""#"translate 0cm ' -0.5cm'"
VPYPE_ROTATE = "--landscape"
VPYPE_READ_MULTILAYER_A4 = "vpype read {infile} layout -h center -v center a4 scaleto 18.5cm 29.7cm {translate} linemerge --tolerance {mergeTol} linesimplify --tolerance {simpleTol} linesort"
VPYPE_WRITE_HPGL_A4 = " write -q {rotate} --page-size a4 --device hp7475a {outHPGL}"

VPYPE_READ_MULTILAYER_A3 = "vpype read {infile} layout -h center -v center a3 scaleto 26.7cm 42cm {translate} linemerge --tolerance {mergeTol} linesimplify --tolerance {simpleTol} linesort"
VPYPE_WRITE_HPGL_A3 = " write -q {rotate} --page-size a3 --device hp7475a {outHPGL}"

HP7475A_SEND_HPGL = "python3 ./hp7475a_send.py -p {port} -b {baud}  {inHPGL}"

EMPTY_SVG_FILE = "./empty.svg"
TEMP_SINGLELAYER_NAMES = ["lay1.svg", "lay2.svg", "lay3.svg", "lay4.svg", "lay5.svg", "lay6.svg"]
TEMP_MULTILAYER_FILENAME = "multiLayer.svg"
TEMP_HPGL_FILENAME = "print.hpgl"

# set to True if you want to test without a printer connected
IS_DUMMY = False

plotArray = {}
printQueue = queue.Queue()
plotLifetime = 30*60



app = Flask(__name__)
@app.route('/uploadMultiSVG', methods = ['POST'])
def uploadMultiSVG():
    global plotArray
    if request.method == 'POST':
        svgFile = request.files['svgFile']
        if(svgFile == ''):
            retVal = {"status":"Please provide an image file in \"svgFile\"", "statusId":-1}
            return json.dumps(retVal),400
        try:
            dirpath = tempfile.mkdtemp() + '/'
            with open(dirpath+TEMP_MULTILAYER_FILENAME, "wb") as svg:
                svg.write(svgFile.read())
        except Exception as e:
            retVal = {"status":"Image could not be written properly!", "error":str(e), "statusId":-1}
            return json.dumps(retVal),400
        else:
            plotId = hex(hash(svgFile))[2:10] # first 8 hex digits of the hash
            plotArray[plotId] = {'rotate':False, 'isA3':False, 'tolerance':"0.1mm", 'dirPath':dirpath, 'status':"Uploaded", 'statusId':STATUS_UPLOADED, 'timestamp':time.time()}
            retVal = {"plotId":plotId}
            return json.dumps(retVal),200

@app.route('/upload6SingleSVG', methods = ['POST'])
def upload6SingleSVG():
    global plotArray
    if request.method == 'POST':
        svgFiles = [request.files.get('svgFile1'),
                    request.files.get('svgFile2'),
                    request.files.get('svgFile3'),
                    request.files.get('svgFile4'),
                    request.files.get('svgFile5'),
                    request.files.get('svgFile6')]
        if(svgFiles[0] == None and svgFiles[1] == None and svgFiles[2] == None and svgFiles[3] == None and svgFiles[4] == None and svgFiles[5] == None):
            retVal = {"status":"Please provide at least one image file in \"svgFiles\"", "statusId":-1}
            return json.dumps(retVal),400
        try:
            dirpath = tempfile.mkdtemp() + '/'
            for i in range (6):
                with open(dirpath+TEMP_SINGLELAYER_NAMES[i], "wb") as svg:
                    if(svgFiles[i] == None):
                        with open(EMPTY_SVG_FILE, "rb") as empty:
                            svg.write(empty.read())
                    else:
                        svg.write(svgFiles[i].read())
            os.system(VPYPE_READ_MULTIPLE_SINGLE_LAYER.format(infile1=dirpath+TEMP_SINGLELAYER_NAMES[0], 
                                                                infile2=dirpath+TEMP_SINGLELAYER_NAMES[1], 
                                                                infile3=dirpath+TEMP_SINGLELAYER_NAMES[2], 
                                                                infile4=dirpath+TEMP_SINGLELAYER_NAMES[3], 
                                                                infile5=dirpath+TEMP_SINGLELAYER_NAMES[4], 
                                                                infile6=dirpath+TEMP_SINGLELAYER_NAMES[5], 
                                                                outfile=dirpath+TEMP_MULTILAYER_FILENAME))
        except Exception as e:
            retVal = {"status":"Image could not be parsed properly!", "error":str(e), "statusId":-1}
            return json.dumps(retVal),400
        else:
            plotId = hex(hash(svgFiles[0]))[2:10] # first 8 hex digits of the hash
            plotArray[plotId] = {'rotate':False, 'isA3':False, 'tolerance':"0.1mm", 'dirPath':dirpath, 'status':"Uploaded", 'statusId':STATUS_UPLOADED, 'timestamp':time.time()}
            retVal = {"plotId":plotId}
            return json.dumps(retVal),200

@app.route('/<string:plotId>/setTolerance', methods = ['POST'])
def setTolerance(plotId):
    global plotArray
    if request.method == 'POST':
        if( plotId not in plotArray ):
            retVal = {"status":"Invalid label id!", "statusId":-1}
            return json.dumps(retVal),400
        tolerance = int(request.form.get('tolerance')) # Between 0 and 255
        if(tolerance < 0 or tolerance > 256):
            retVal = {"status":"Invalid tolerance! Larger than 255 or smaller than 0", "statusId":-1}
            return json.dumps(retVal),400
        try:
            plotArray[plotId]['tolerance'] = str(tolerance*2 / 255)+"mm"
            retVal = {"status":"Tolerance set to: {}".format(plotArray[plotId]['tolerance']), "statusId":plotArray[plotId]['statusId']}
            plotArray[plotId]['timestamp'] = time.time()
            return json.dumps(retVal),200
        except Exception as e:
            retVal = {"status":"Label array could not be read", "error":str(e), "statusId":plotArray[plotId]['statusId']}
            return json.dumps(retVal),400

@app.route('/<string:plotId>/rotatePlot', methods = ['POST'])
def rotatePlot(plotId):
    global plotArray
    if request.method == 'POST':
        if( plotId not in plotArray ):
            retVal = {"status":"Invalid plot id!", "statusId":-1}
            return json.dumps(retVal),400
        try:
            plotArray[plotId]['rotate'] = not plotArray[plotId]['rotate']
            retVal = {"status":"Image rotated 90 degrees", "statusId":plotArray[plotId]['statusId']}
            return json.dumps(retVal),200
        except Exception as e:
            retVal = {"status":"Image could not be parsed properly!", "error":str(e), "statusId":plotArray[plotId]['statusId']}

@app.route('/<string:plotId>/setSizeOfPlot', methods = ['POST'])
def setSizeOfPlot(plotId):
    global plotArray
    if request.method == 'POST':
        if( plotId not in plotArray ):
            retVal = {"status":"Invalid label id!", "statusId":-1}
            return json.dumps(retVal),400
        try:
            sizeStr = request.form.get('paperSize') # a3 and a4 supported
            if(sizeStr == "a3"):
                plotArray[plotId]['isA3'] = True
            elif(sizeStr == "a4"):
                plotArray[plotId]['isA3'] = False   
            else:
                raise ValueError("Invalid oaper size! Only 'a3' and 'a4' are supported")      
            retVal = {"status":"Paper size set to: {}".format(sizeStr), "statusId":plotArray[plotId]['statusId']}
            plotArray[plotId]['timestamp'] = time.time()
            return json.dumps(retVal),200
        except Exception as e:
            retVal = {"status":"An error occured while setting the paper size", "error":str(e), "statusId":plotArray[plotId]['statusId']}
            return json.dumps(retVal),400

@app.route('/<string:plotId>/previewPlot', methods = ['GET'])
def previewPlot(plotId):
    global plotArray
    if request.method == 'GET':
        if( plotId not in plotArray ):
            retVal = {"status":"Invalid plot id!", "statusId":-1}
            return json.dumps(retVal),400
        try:
            dirpath = plotArray[plotId]['dirPath']
            generateHPGLFile(plotId)
            myimage = ""
            with open(dirpath+TEMP_HPGL_FILENAME, "rb") as svg:
                buffer =  BytesIO(svg.read())
                myimage = buffer.getvalue()   
            plotArray[plotId]['timestamp'] = time.time()
            return myimage,200
        except Exception as e:
            print(e)
            retVal = {"status":"Image could not be parsed properly!", "error":str(e), "statusId":plotArray[plotId]['statusId']}
            return json.dumps(retVal),400

@app.route('/<string:plotId>/getStatus', methods = ['GET'])
def getStatus(plotId):
    global plotArray
    if request.method == 'GET':
        if( plotId not in plotArray ):
            retVal = {"status":"Invalid plot id!", "statusId":-1}
            return json.dumps(retVal),400
        retVal = {"status":plotArray[plotId]['status'], "statusId":plotArray[plotId]['statusId']}
        plotArray[plotId]['timestamp'] = time.time()
        return json.dumps(retVal),200

@app.route('/<string:plotId>/printPlot', methods = ['POST'])
def printPlot(plotId):
    global plotArray
    if request.method == 'POST':
        if( plotId not in plotArray ):
            retVal = {"status":"Invalid plot id!", "statusId":-1}
            return json.dumps(retVal),400
        if(not printQueue.empty()):
            retVal = {"status":"Already printing something!", "statusId":STATUS_ALREADY_PRINTING}
            return json.dumps(retVal),400
        try:
            plotArray[plotId]['status'] = "Starting print!"
            plotArray[plotId]['statusId'] = STATUS_START_PRINT
            printQueue.put(plotId)
            retVal = {"status":"Starting Print!", "statusId":plotArray[plotId]['statusId']}
            plotArray[plotId]['timestamp'] = time.time()
            return json.dumps(retVal),200
        except Exception as e:
            print(e)
            retVal = {"status":"Image could not be parsed properly!", "error":str(e), "statusId":plotArray[plotId]['statusId']}
            return json.dumps(retVal),400

@app.after_request
def after_request(response):
    header = response.headers
    header['Access-Control-Allow-Origin'] = '*'
    return response

def generateHPGLFile(plotId):
    dirpath = plotArray[plotId]['dirPath']
    rotateStr = ""
    translateStr = VPYPE_A4_TRANSLATE_PORTRAIT
    if(plotArray[plotId]['rotate']):
        rotateStr = VPYPE_ROTATE
        translateStr = VPYPE_A4_TRANSLATE_LANDSCAPE
    if(plotArray[plotId]['isA3']):
        os.system(VPYPE_READ_MULTILAYER_A3.format(infile=dirpath+TEMP_MULTILAYER_FILENAME, 
                                                    translate=translateStr,
                                                    mergeTol=plotArray[plotId]['tolerance'], 
                                                    simpleTol=plotArray[plotId]['tolerance']) +
                    VPYPE_WRITE_HPGL_A3.format(rotate=rotateStr, outHPGL=dirpath+TEMP_HPGL_FILENAME))
    else:
        os.system(VPYPE_READ_MULTILAYER_A4.format(infile=dirpath+TEMP_MULTILAYER_FILENAME, 
                                                    translate=translateStr,
                                                    mergeTol=plotArray[plotId]['tolerance'], 
                                                    simpleTol=plotArray[plotId]['tolerance']) +
                    VPYPE_WRITE_HPGL_A4.format(rotate=rotateStr, outHPGL=dirpath+TEMP_HPGL_FILENAME))

def printPlotThread(plotQueue):
    while True:
        time.sleep(1)
        if not plotQueue.empty():
            plotId = plotQueue.get()
            print("Starting print of plot: "+str(plotId))
            try:
                dirpath = plotArray[plotId]['dirPath']
                generateHPGLFile(plotId)
                os.system(HP7475A_SEND_HPGL.format(port=HP7475_TTY_PORT, baud=HP7475_TTY_BAUD, inHPGL=dirpath+TEMP_HPGL_FILENAME))
                plotArray[plotId]['status'] = "Print Done!"
                plotArray[plotId]['statusId'] = STATUS_DONE
            except Exception as e:
                print(e)
                plotArray[plotId]['status'] = "Printing failed with exception: "+str(e)
                plotArray[plotId]['statusId'] = STATUS_PRINT_FAILED
            finally:
                shutil.rmtree(dirpath, ignore_errors=True)
                plotQueue.task_done()

def garbageCollectionThread():
    """Removes all plots older than `plotLifetime` from the `plotArray`"""
    while True:
        expiredPlots = []
        for plotId,plot in enumerate(plotArray):
            if(plot['timestamp'] - time.time() > plotLifetime):
                expiredPlots.append(plotId)
        for plotId in expiredPlots:
            shutil.rmtree(plotArray[plotId]['dirPath'], ignore_errors=True)
            plotArray.pop(plotId)
        time.sleep(plotLifetime)

if __name__ == '__main__':
    pLT = Thread(target=printPlotThread,args=(printQueue,))
    pLT.start()
    gCT = Thread(target=garbageCollectionThread,args=())
    gCT.start()
    app.run(host='0.0.0.0', port=1050)
