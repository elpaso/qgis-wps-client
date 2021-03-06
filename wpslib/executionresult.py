# -*- coding: utf-8 -*-
"""
 /***************************************************************************
   QGIS Web Processing Service Plugin
  -------------------------------------------------------------------
 Date                 : 09 November 2009
 Copyright            : (C) 2009 by Dr. Horst Duester
 email                : horst dot duester at kappasys dot ch

  ***************************************************************************
  *                                                                         *
  *   This program is free software; you can redistribute it and/or modify  *
  *   it under the terms of the GNU General Public License as published by  *
  *   the Free Software Foundation; either version 2 of the License, or     *
  *   (at your option) any later version.                                   *
  *                                                                         *
  ***************************************************************************/
"""

from PyQt4.QtCore import *
from PyQt4.QtNetwork import *
from PyQt4.QtGui import QApplication, QMessageBox
from PyQt4 import QtXml
from PyQt4.QtXmlPatterns import QXmlQuery
from qgis.core import QgsNetworkAccessManager, QgsProviderRegistry, QgsRasterLayer, QgsMapLayerRegistry
from functools import partial
from wps.wpslib.processdescription import getFileExtension, isMimeTypeOWS
import tempfile
import base64
import wps.apicompat


# Execute result example:
#
#<?xml version="1.0" encoding="utf-8"?>
#<wps:ExecuteResponse xmlns:wps="http://www.opengis.net/wps/1.0.0" xmlns:ows="http://www.opengis.net/ows/1.1" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.opengis.net/wps/1.0.0 http://schemas.opengis.net/wps/1.0.0/wpsExecute_response.xsd" service="WPS" version="1.0.0" xml:lang="eng" serviceInstance="http://www.kappasys.ch/pywps?service=WPS&amp;request=GetCapabilities&amp;version=1.0.0" statusLocation="http://www.kappasys.ch/pywps/wpsoutputs/pywps-136243739626.xml">
#    <wps:Process wps:processVersion="1.0">
#        <ows:Identifier>returner</ows:Identifier>
#        <ows:Title>Return process</ows:Title>
#        <ows:Abstract>This is demonstration process of PyWPS, returns the same file, it gets on input, as the output.</ows:Abstract>
#    </wps:Process>
#    <wps:Status creationTime="2013-03-04T23:49:56Z">
#        <wps:ProcessSucceeded>PyWPS Process returner successfully calculated</wps:ProcessSucceeded>
#    </wps:Status>
#    <wps:ProcessOutputs>
#        <wps:Output>
#            <ows:Identifier>output2</ows:Identifier>
#            <ows:Title>Output vector data</ows:Title>
#            <wps:Reference xlink:href="http://www.kappasys.ch/pywps/wpsoutputs/output2-30429" mimeType="text/xml"/>
#        </wps:Output>
#        <wps:Output>
#            <ows:Identifier>text</ows:Identifier>
#            <ows:Title>Output literal data</ows:Title>
#            <wps:Data>
#                <wps:LiteralData dataType="integer">33</wps:LiteralData>
#            </wps:Data>
#        </wps:Output>
#        <wps:Output>
#            <ows:Identifier>output1</ows:Identifier>
#            <ows:Title>Output vector data</ows:Title>
#            <wps:Reference xlink:href="http://www.kappasys.ch/pywps/wpsoutputs/output1-30429" mimeType="text/xml"/>
#        </wps:Output>
#    </wps:ProcessOutputs>
#</wps:ExecuteResponse>


def decodeBase64(infileName,  mimeType="", tmpDir=None):
    try:
        tmpFile = tempfile.NamedTemporaryFile(
            prefix="base64", suffix=getFileExtension(mimeType), dir=tmpDir, delete=False)
        infile = open(infileName)
        outfile = open(tmpFile.name, 'w')
        base64.decode(infile, outfile)

        infile.close()
        outfile.close()
    except:
        raise

    return tmpFile.name


class ExecutionResult(QObject):
    """
    Send request XML and process result
    """

    fetchingResult = pyqtSignal(int)
    killed = pyqtSignal()

    def __init__(self, literalResultCallback, resultFileCallback, successResultCallback, errorResultCallback, streamingHandler, progressBar=None):
        QObject.__init__(self)
        self._getLiteralResult = literalResultCallback
        self._resultFileCallback = resultFileCallback
        self._successResultCallback = successResultCallback
        self._errorResultCallback = errorResultCallback
        self._streamingHandler = streamingHandler
        self._processExecuted = False
        self.progressBar = progressBar
        self.noFilesToFetch = 0

    def open_wmts(self, name, capabilites_url):
        # Add new HTTPConnection like in source
        # https://github.com/qgis/QGIS/blob/master/src/gui/qgsnewhttpconnection.cpp

        s = QSettings()

        s.setValue(u'Qgis/WMS/{0}/password'.format(name), '')
        s.setValue(u'Qgis/WMS/{0}/username'.format(name), '')
        # refer to
        # https://github.com/qgis/QGIS/blob/master/src/gui/qgsnewhttpconnection.cpp#L229-L247
        s.setValue(u'Qgis/connections-wms/{0}/dpiMode'.format(name), 7)
        s.setValue(
            u'Qgis/connections-wms/{0}/ignoreAxisOrientation'.format(name), False)
        s.setValue(
            u'Qgis/connections-wms/{0}/ignoreGetFeatureInfoURI'.format(name), False)
        s.setValue(
            u'Qgis/connections-wms/{0}/ignoreGetMapURI'.format(name), False)
        s.setValue(
            u'Qgis/connections-wms/{0}/invertAxisOrientation'.format(name), False)
        s.setValue(u'Qgis/connections-wms/{0}/referer'.format(name), '')
        s.setValue(
            u'Qgis/connections-wms/{0}/smoothPixmapTransform'.format(name), False)
        s.setValue(
            u'Qgis/connections-wms/{0}/url'.format(name), capabilites_url)

        s.setValue(u'Qgis/connections-wms/selected', name)

        # create new dialog
        wms_dlg = QgsProviderRegistry.instance().selectWidget("wms")

        def addRasterLayer(url, name, provider):
            layer = QgsRasterLayer(url, name, provider)
            QgsMapLayerRegistry.instance().addMapLayer(layer)

        QObject.connect(wms_dlg, SIGNAL("addRasterLayer( QString const &, QString const &, QString const & )"),
                        addRasterLayer)

        self.showProgressBar(True,  100, 'finished')

        wms_dlg.show()

    def open_wfs(self, name, capabilites_url):
        # Add new HTTPConnection like in source
        # https://github.com/qgis/QGIS/blob/master/src/gui/qgsnewhttpconnection.cpp
        # https://github.com/qgis/QGIS/blob/79616fd8d8285b4eb93adafdfcb97a3e429b832e/src/app/qgisapp.cpp#L3783

        # remove additional url parameters, otherwise adding wfs works the frist time only
        # https://github.com/qgis/QGIS/blob/9eee12111567a84f4d4de7e020392b3c01c28598/src/gui/qgsnewhttpconnection.cpp#L199-L214
        url = QUrl(capabilites_url)
        url.removeQueryItem('SERVICE')
        url.removeQueryItem('REQUEST')
        url.removeQueryItem('FORMAT')
        url.removeQueryItem('service')
        url.removeQueryItem('request')
        url.removeQueryItem('format')
        # also remove VERSION: shouldn't be necessary, but QGIS sometimes seems
        # to append version=1.0.0
        url.removeQueryItem('VERSION')
        url.removeQueryItem('version')

        capabilites_url = url.toString()
        self.msg_log(u'add WFS: Name={0}, base URL={1}'.format(
            name, capabilites_url))

        s = QSettings()

        self.msg_log(u'existing WFS url: {0}'.format(
            s.value(u'Qgis/connections-wfs/{0}/url'.format(name), '')))

        key_user = u'Qgis/WFS/{0}/username'.format(name)
        key_pwd = u'Qgis/WFS/{0}/password'.format(name)
        key_referer = u'Qgis/connections-wfs/{0}/referer'.format(name)
        key_url = u'Qgis/connections-wfs/{0}/url'.format(name)

        s.remove(key_user)
        s.remove(key_pwd)
        s.remove(key_referer)
        s.remove(key_url)
        s.sync()

        s.setValue(key_user, '')
        s.setValue(key_pwd, '')
        s.setValue(key_referer, '')
        s.setValue(key_url, capabilites_url)

        s.setValue(u'Qgis/connections-wfs/selected', name)

        # create new dialog
        wfs_dlg = QgsProviderRegistry.instance().selectWidget("WFS")

        def addVectorLayer(url, name, provider):
            layer = QgsVectorLayer(url, name, provider)
            QgsMapLayerRegistry.instance().addMapLayer(layer)

        QObject.connect(wfs_dlg, SIGNAL("addVectorLayer( QString const &, QString const &, QString const & )"),
                        addVectorLayer)

        wfs_dlg.show()

    def executeProcess(self, processUrl, requestXml):
        self._processExecuted = False
        self.noFilesToFetch = 0

        postData = QByteArray()
        postData.append(requestXml)

        scheme = processUrl.scheme()
        path = processUrl.path()
        server = processUrl.host()
        port = processUrl.port()

        processUrl.removeQueryItem('Request')
        processUrl.removeQueryItem('identifier')
        processUrl.removeQueryItem('Version')
        processUrl.removeQueryItem('Service')

        qDebug("Post URL=" + pystring(processUrl))

        thePostHttp = QgsNetworkAccessManager.instance()
        request = QNetworkRequest(processUrl)
        request.setHeader(QNetworkRequest.ContentTypeHeader, "text/xml")
        self.thePostReply = thePostHttp.post(request, postData)
        self.thePostReply.finished.connect(
            partial(self.resultHandler, self.thePostReply))

    def finished(self):
        return self._processExecuted and (self.noFilesToFetch == 0)

    def resultHandler(self, reply):
        """Handle the result of the WPS Execute request and add the outputs as new
           map layers to the registry or open an information window to show literal
           outputs."""
        resultXML = reply.readAll().data()
        reply.deleteLater()
        qDebug(resultXML)
        self.parseResult(resultXML)
        self._processExecuted = True
        return True

    def parseResult(self, resultXML):
        self.doc = QtXml.QDomDocument()
        self.doc.setContent(resultXML,  True)
        resultErrorNodeList = self.doc.elementsByTagNameNS(
            "http://www.opengis.net/ows/1.1", "ExceptionReport")
        if resultErrorNodeList.size() > 0:
            #            for i in range(resultErrorNodeList.size()):
            #              f_element = resultErrorNodeList.at(i).toElement()
            #              exceptionText = pystring(f_element.elementsByTagNameNS("http://www.opengis.net/ows/1.1","ExceptionText").at(0).toElement().text()).strip()
            #              QMessageBox.information(None, 'Process Exception',  exceptionText)
            return self.errorHandler(resultXML)

        resultNodeList = self.doc.elementsByTagNameNS(
            "http://www.opengis.net/wps/1.0.0", "Output")

        # TODO: Check if the process does not run correctly before
        if resultNodeList.size() > 0:
            for i in range(resultNodeList.size()):
                f_element = resultNodeList.at(i).toElement()
                identifier = pystring(f_element.elementsByTagNameNS(
                    "http://www.opengis.net/ows/1.1", "Identifier").at(0).toElement().text()).strip()
                # Fetch the referenced complex data
                if f_element.elementsByTagNameNS("http://www.opengis.net/wps/1.0.0", "Reference").size() > 0:
                    reference = f_element.elementsByTagNameNS(
                        "http://www.opengis.net/wps/1.0.0", "Reference").at(0).toElement()

                    # Get the reference
                    fileLink = reference.attribute("href", "0")

                    # Try with namespace if not successful
                    if fileLink == '0':
                        fileLink = reference.attributeNS(
                            "http://www.w3.org/1999/xlink", "href", "0")
                    if fileLink == '0':
                        QMessageBox.warning(None, '',
                                            pystring(QApplication.translate("QgsWps", "WPS Error: Unable to download the result of reference: ")) + pystring(fileLink))
                        return False

                    # Get the mime type of the result
                    self.mimeType = pystring(
                        reference.attribute("mimeType", "0")).lower()

                    # Get the encoding of the result, it can be used decoding
                    # base64
                    encoding = pystring(
                        reference.attribute("encoding", "")).lower()
                    schema = pystring(
                        reference.attribute("schema", "")).lower()

                    if fileLink != '0':
                        if "playlist" in self.mimeType:  # Streaming based process?
                            self._streamingHandler(encoding, fileLink)
                        else:  # Conventional processes
                            self.fetchResult(encoding, schema,
                                             fileLink, identifier)

                elif f_element.elementsByTagNameNS("http://www.opengis.net/wps/1.0.0", "ComplexData").size() > 0:
                    complexData = f_element.elementsByTagNameNS(
                        "http://www.opengis.net/wps/1.0.0", "ComplexData").at(0).toElement()

                    # Get the mime type of the result
                    self.mimeType = pystring(
                        complexData.attribute("mimeType", "0")).lower()

                    # Get the encoding of the result, it can be used decoding
                    # base64
                    encoding = pystring(
                        complexData.attribute("encoding", "")).lower()
                    schema = pystring(
                        reference.attribute("schema", "")).lower()

                    if "playlist" in self.mimeType:
                        playlistUrl = f_element.elementsByTagNameNS(
                            "http://www.opengis.net/wps/1.0.0", "ComplexData").at(0).toElement().text()
                        self._streamingHandler(encoding, playlistUrl)

                    else:  # Other ComplexData are not supported by this WPS client
                        QMessageBox.warning(None, '',
                                            pystring(QApplication.translate("QgsWps", "WPS Error: The mimeType '" + self.mimeType + "' is not supported by this client")))

                elif f_element.elementsByTagNameNS("http://www.opengis.net/wps/1.0.0", "LiteralData").size() > 0:
                    literalText = f_element.elementsByTagNameNS(
                        "http://www.opengis.net/wps/1.0.0", "LiteralData").at(0).toElement().text()
                    self._getLiteralResult(identifier, literalText)
                else:
                    QMessageBox.warning(None, '',
                                        pystring(QApplication.translate("QgsWps", "WPS Error: Missing reference or literal data in response")))
        else:
            status = self.doc.elementsByTagName("Status")
            try:
                child = status.at(0).firstChildElement()
                if child.localName() == "ProcessSucceeded":
                    self._successResultCallback()
                else:
                    self.errorHandler(child.text())
#                    self.errorHandler(resultXML)
            except:
                return self.errorHandler(resultXML)

    def fetchResult(self, encoding, schema,  fileLink, identifier):
        self.noFilesToFetch += 1

        if isMimeTypeOWS(self.mimeType):
            record = isMimeTypeOWS(self.mimeType)
            if record['PROVIDER'] == 'wms':
                # ADD the WMS to the project
                self.open_wmts(identifier, fileLink)
                self.fetchingResult.emit(self.noFilesToFetch)
                return
            if record['PROVIDER'] == 'wfs':
                # ADD the WMS to the project
                self.open_wfs(identifier, fileLink)
                self.fetchingResult.emit(self.noFilesToFetch)
                return

        url = QUrl(fileLink)

        self.myHttp = QgsNetworkAccessManager.instance()
        self.theReply = self.myHttp.get(QNetworkRequest(url))
        self.fetchingResult.emit(self.noFilesToFetch)

        # Append encoding to 'finished' signal parameters
        self.encoding = encoding
        self.schema = schema
        self.theReply.finished.connect(partial(
            self.getResultFile, identifier, self.mimeType, encoding, schema,  self.theReply))
        self.theReply.downloadProgress.connect(
            lambda done,  all,  status="download": self.showProgressBar(done,  all,  status))

    def errorDescription(self, errorNo):
        """Return a text representation of the network error"""
        if errorNo == QNetworkReply.ConnectionRefusedError:
            return "the remote server refused the connection (the server is not accepting requests)"
        if errorNo == QNetworkReply.RemoteHostClosedError:
            return "the remote server closed the connection prematurely, before the entire reply was received and processed"
        if errorNo == QNetworkReply.HostNotFoundError:
            return "the remote host name was not found (invalid hostname)"
        if errorNo == QNetworkReply.TimeoutError:
            return "the connection to the remote server timed out"
        if errorNo == QNetworkReply.OperationCanceledError:
            return "the operation was canceled via calls to abort() or close() before it was finished."
        if errorNo == QNetworkReply.SslHandshakeFailedError:
            return "the SSL/TLS handshake failed and the encrypted channel could not be established. The sslErrors() signal should have been emitted."
        if errorNo == QNetworkReply.TemporaryNetworkFailureError:
            return "the connection was broken due to disconnection from the network, however the system has initiated roaming to another access point. The request should be resubmitted and will be processed as soon as the connection is re-established."
        if errorNo == QNetworkReply.ProxyConnectionRefusedError:
            return "the connection to the proxy server was refused (the proxy server is not accepting requests)"
        if errorNo == QNetworkReply.ProxyConnectionClosedError:
            return "the proxy server closed the connection prematurely, before the entire reply was received and processed"
        if errorNo == QNetworkReply.ProxyNotFoundError:
            return "the proxy host name was not found (invalid proxy hostname)"
        if errorNo == QNetworkReply.ProxyTimeoutError:
            return "the connection to the proxy timed out or the proxy did not reply in time to the request sent"
        if errorNo == QNetworkReply.ProxyAuthenticationRequiredError:
            return "the proxy requires authentication in order to honour the request but did not accept any credentials offered (if any)"
        if errorNo == QNetworkReply.ContentAccessDenied:
            return "the access to the remote content was denied (similar to HTTP error 401)"
        if errorNo == QNetworkReply.ContentOperationNotPermittedError:
            return "the operation requested on the remote content is not permitted"
        if errorNo == QNetworkReply.ContentNotFoundError:
            return "the remote content was not found at the server (similar to HTTP error 404)"
        if errorNo == QNetworkReply.AuthenticationRequiredError:
            return "the remote server requires authentication to serve the content but the credentials provided were not accepted (if any)"
        if errorNo == QNetworkReply.ContentReSendError:
            return "the request needed to be sent again, but this failed for example because the upload data could not be read a second time."
        if errorNo == QNetworkReply.ProtocolUnknownError:
            return "the Network Access API cannot honor the request because the protocol is not known"
        if errorNo == QNetworkReply.ProtocolInvalidOperationError:
            return "the requested operation is invalid for this protocol"
        if errorNo == QNetworkReply.UnknownNetworkError:
            return "an unknown network-related error was detected"
        if errorNo == QNetworkReply.UnknownProxyError:
            return "an unknown proxy-related error was detected"
        if errorNo == QNetworkReply.UnknownContentError:
            return "an unknown error related to the remote content was detected"
        if errorNo == QNetworkReply.ProtocolFailure:
            return "a breakdown in protocol was detected (parsing error, invalid or unexpected responses, etc.)"
        return "Unknown network error"


    def getResultFile(self, identifier, mimeType, encoding, schema,  reply):
        # Check if there is redirection
        if reply.error() != QNetworkReply.NoError:
            QMessageBox.critical(None, "WPS Response error", "There was an error processing the WPS response URL %s: %s" % (reply.url().toString(), self.errorDescription(reply.error())))
            self.noFilesToFetch = 0
        else:
            try:
                reDir = reply.attribute(
                    QNetworkRequest.RedirectionTargetAttribute).toUrl()
                if not reDir.isEmpty():
                    self.fetchResult(encoding, schema,  reDir, identifier)
                    return

            except:
                reDir = reply.attribute(QNetworkRequest.RedirectionTargetAttribute)
                if reDir is not None:
                    self.fetchResult(encoding, schema,  reDir, identifier)
                    return

            self._resultFileCallback(identifier, mimeType,
                                     encoding, schema,  reply)
            self.noFilesToFetch -= 1

        reply.deleteLater()

    def handleEncoded(self, file, mimeType, encoding,  schema):
        # Decode?
        if schema == "base64" or encoding == 'base64':
            return decodeBase64(file, mimeType)
        else:
            return file

    def showProgressBar(self,  done,  total, status):

        complete = status == "aborted" or status == "finished" or status == "error"

        self.progressBar.setRange(done, total)
        if status == "upload" and done == total:
            status = "processing"
            done = total = 0

        if complete:
            self.progressBar.setRange(0, 100)
            self.progressBar.setValue(100)
        else:
            self.progressBar.setRange(0, total)
            self.progressBar.setValue(done)

    def errorHandler(self, resultXML):
        if resultXML:
            qDebug(resultXML)
            query = QXmlQuery(QXmlQuery.XSLT20)
            xslFile = QFile(":/plugins/wps/exception.xsl")
            xslFile.open(QIODevice.ReadOnly)
            bRead = query.setFocus(resultXML)
            query.setQuery(xslFile)
            exceptionHtml = query.evaluateToString()
            if exceptionHtml is None:
                qDebug("Empty result from exception.xsl")
                exceptionHtml = resultXML
            self._errorResultCallback(exceptionHtml)
            xslFile.close()
        return False
