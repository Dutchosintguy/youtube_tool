"""
A tool for extracting useful information from youtube video's, like comments, or subtitles.

note about youtube id's:
    * id's consist of: A-Za-z0-9-_
    * a video id has 11 characters
    * a playlist id has 24 characters
"""

import urllib.request
import urllib.parse
import http.cookiejar
import re
import json
import sys
import html

from xml.parsers.expat import ParserCreate

import http.client

def getitembymember(a, member):
    for item in a:
        if member in item:
            return item


def getitem(d, *path):
    """
    Traverse a nested python object, path items select which object is selected:
     * a tuple: selects a dictionary from a list which contains the specified key
     * an integer: select the specified item from a list.
     * a string: select the specified item from a dictionary.
    """
    for k in path:
        if type(k) == tuple:
            d = getitembymember(d, *k)
        elif type(k) == int:
            d = d[k]
        else:
            d = d.get(k)

        if d is None:
            return
    return d


class Youtube:
    """
    Class which knows how to get information from youtune video's
    """
    def __init__(self, args):
        self.args = args
        cj = http.cookiejar.CookieJar()
        handlers = [urllib.request.HTTPCookieProcessor(cj)]
        if args.debug:
            handlers.append(urllib.request.HTTPSHandler(debuglevel=1))
        self.opener = urllib.request.build_opener(*handlers)


    def httpreq(self, url, data=None):
        """
        does GET or POST request to youtube.
        """
        hdrs = {
            "x-youtube-client-name": "1",
            "x-youtube-client-version": "2.20200422.04.00",
        }

        req = urllib.request.Request(url, headers=hdrs)

        kwargs = dict()
        if data:
            kwargs["data"] = data

        response = self.opener.open(req, **kwargs)
        return response.read()

    def getcomments(self, contclick, xsrf):
        """
        Returns comments for the specified continuation parameter.
        """
        cont, click = contclick
        url = "https://www.youtube.com/comment_service_ajax"
        query = {
            "action_get_comments": 1,
            "pbj": 1,
            "ctoken": cont,
            "continuation": cont,
            "itct": click,
        }

        postdata = urllib.parse.urlencode({ "session_token":xsrf })
        return self.httpreq(url + "?" + urllib.parse.urlencode(query), postdata.encode('ascii') )

    def browse(self, contclick):
        """
        Returns videos for the specified continuation parameter.
        """
        cont, click = contclick
        url = "https://www.youtube.com/browse_ajax"
        query = {
            "ctoken": cont,
            "continuation": cont,
            "itct": click,
        }

        return self.httpreq(url + "?" + urllib.parse.urlencode(query))


    def getpageinfo(self, yturl):
        """
        Returns the youtube configuration object.
        """
        ytcfgtext = self.httpreq(yturl + "&pbj=1")
        if self.args.debug:
            print("============ youtube config")
            print(ytcfgtext.decode('utf-8'))
            print()

        # playerResponse, microformat
        #   -> viewCount, publishDate, uploadDate
        return json.loads(ytcfgtext)

    def getconfigfromhtml(self, ythtml):
        """
        Alternative method of extracting the config object.
        By parsing the html page returned by youtube.
        """
        if self.args.debug:
            print("============ youtube page")
            print(ythtml.decode('utf-8'))
            print()

        m = re.search(br'ytplayer.config = (.*?);ytplayer.load', ythtml)
        if not m:
            print("could not find config")
            return
        cfgtext = m.group(1)
        if self.args.debug:
            print("========== config json")
            print(cfgtext.decode('utf-8'))
            print()

        cfg = json.loads(cfgtext)
        
        playertext = cfg['args']['player_response']
        if self.args.debug:
            print("========== player json")
            print(playertext)
            print()
        return json.loads(playertext)




class CommentReader:
    """
    class which can recursively print comments
    """
    def __init__(self, args, yt, cfg):
        self.args = args
        self.yt = yt
        self.contclick, self.xsrf = self.getcommentinfo(cfg)

    def recursecomments(self, cc=None, level=0):
        if not cc:
            cc = self.contclick
        while cc:
            cmtjson = self.yt.getcomments(cc, self.xsrf)
            if self.args.debug:
                print("============ comment req")
                print(cmtjson.decode('utf-8'))
                print()

            js = json.loads(cmtjson)

            cmtlist, cc = self.extractcomments(js) 

            for author, runs, subcc in cmtlist:
                print("---" * (level+1) + ">", author, runs)
                if subcc:
                    self.recursecomments(subcc, level+1)


    def getcontinuation(self, p):
        p = getitem(p, "continuations", 0, "nextContinuationData")
        if not p:
            return
        return p["continuation"], p["clickTrackingParams"]

    def getcommentinfo(self, cfg):
        """
        Find the base parameters for querying the video's comments.

        Note: the config structure is like this:

        [ {
            "response": { "contents": { "twoColumnWatchNextResults": { "results": { "results": { "contents": [
                ...
                {
                    "itemSectionRenderer": { "continuations": [
                        {
                            "nextContinuationData": {
                                "continuation": "EiYSC00xQjNnQVRTMEdFwAEAyAEA4AECogINKP___________wFAABgG",
                                "clickTrackingParams": "CMwBEMm3AiITCKKxgqzH_ugCFUFO4Aodp_gHYQ==",
                            }
                        }
                    ] }
                }
            ] } } } } }
        } ]
        """
        item = getitem(cfg, ("response",), "response", "contents", "twoColumnWatchNextResults", "results", "results", "contents")
        cont = self.getcontinuation(getitem(item, ("itemSectionRenderer",), "itemSectionRenderer")) 
        xsrf = getitem(cfg, ("response",), "xsrf_token")

        return cont, xsrf

    def getcomment(self, p):
        """
        Return info for a single comment.

        {
            "commentThreadRenderer": {
                "comment": { "commentRenderer": {
                    "authorText": {
                        "simpleText": "Kylie Lees"
                    },
                    "contentText": {
                        "runs": [ { "text": "..." } ]
                    }
                } }
                "replies": {
                    "commentRepliesRenderer": {
                        "continuations": [
                            {
                                "nextContinuationData": {
                                    "continuation": "EiYSC00xQjNnQVRTMEdFwAEAyAEA4AECogINKP___________wFAABgGMk0aSxIaVWd3LWxrZnhHR0dhRWN2MGNRRjRBYUFCQWciAggAKhhVQzNLRW9Nek56OGVZbndCQzM0UmFLQ1EyC00xQjNnQVRTMEdFQAFICg%3D%3D",
                                    "clickTrackingParams": "CPQBEMm3AiITCPO55r7H_ugCFYz2VQodMOYDtg==",
                                    "label": {
                                        "runs": [
                                            {
                                                "text": "Show more replies"
                                            }
                                        ]
                                    }
                                }
                            }
                        ],
                    }
                }
            }
        }
        """
        if "commentThreadRenderer" in p:
            p = p["commentThreadRenderer"]

        c = p
        r = p
        if "comment" in c:
            c = c["comment"]
        if "commentRenderer" in c:
            c = c["commentRenderer"]
        if "replies" in r:
            r = r["replies"]

        author = getitem(c,  "authorText", "simpleText")
        content = getitem(c,  "contentText", "runs")
        replies = getitem(r,  "commentRepliesRenderer")
        if replies:
            cont = self.getcontinuation(replies)
        else:
            cont = None

        return author, content, cont

    def extractcomments(self, js):
        """
        Extract a list of comments from comment dictionary

        {
            "response": { "continuationContents": { "itemSectionContinuation": {
                "contents": [ ... ],
                "continuations": [ {
                    "nextContinuationData": {
                        "continuation": "EiYSC00xQjNnQVRTMEdFwAEAyAEA4AECogINKP___________wFAABgGMpEDCvsCQURTSl9pM2ZXc3pUaUZTaXBuYWRHRGlOSnQtdWp0M0JaRElfSmxHb3JJc2ZFdTFBUVo5dFF2aGpZTExYRElkMUs3YUV2RWJpYnY0MlJwU1doN1FIWmp2VkhralRCbWFUQ19LRkhFWnB5aVdEOW0wdTlvQkRUV1Q0RjNYRklkaE5PeGFRd09zRDE1S19vcVdFVlVhQ3dfTWh3SzN3dlN6Y2xVXzk0R3hSbDhuVHRfQUp5VGpVaVR6OWltQ2ozTVpPMDgzNlNsT3VBUVFyUnduU0xwZ1hZUGtWZkJWcXhiVXdEYVNZSWM3ZWxjSG5SQXNrVUxONFh0ZkNnUXRBWHBsQ2FFLUwxM1plZ2NUQlp4dW9SMktuWkgybHdtYk9LWHNVSDM0Y2oyWjRwcVo4Y3JGcnVtVThwekJPUXpwQVk4R2hsQmduVHNraElKYmFGQktwa2o0U1FVLURCTVZSTWdoWk1qQWlVakt1Smw1MExSRklqOF9tQ2djRm5fWSIPIgtNMUIzZ0FUUzBHRTAAKBQ%3D",
                        "clickTrackingParams": "CAkQybcCIhMI87nmvsf-6AIVjPZVCh0w5gO2"
                    }
                } ]
                "header" : {
                    "commentsHeaderRenderer": {
                        "commentsCount": { "simpleText": "267" },
                    }
                }
            } } }
        }
        """
        p = getitem(js, "response", "continuationContents")
        if "itemSectionContinuation" in p:
            p = p["itemSectionContinuation"]
        elif "commentRepliesContinuation" in p:
            p = p["commentRepliesContinuation"]

        cmtlist = []
        for c in p["contents"]:
            cmtlist.append(self.getcomment(c))

        # header.commentsHeaderRenderer -> commentsCount  at same level as 'contents'

        return cmtlist, self.getcontinuation(p)


class SubtitleReader:
    """
    class which can print a video's subtitles
    """
    def __init__(self, args, yt, cfg):
        self.args = args
        self.yt = yt
        self.cfg = cfg

    def output(self):
        js = getitem(self.cfg, ("playerResponse",), "playerResponse")
        p = getitem(js, "captions", "playerCaptionsTracklistRenderer", "captionTracks")
            
        if not p:
            print("no subtitles found")
            return

        captiontracks = p
        for ct in captiontracks:
            name = ct["name"]["simpleText"]
            ttxml = self.yt.httpreq(ct["baseUrl"])
            if self.args.debug:
                print("========== timedtext xml")
                print(ttxml.decode('utf-8'))
                print()
            tt = self.extracttext(ttxml)

            if self.args.srt:
                self.output_srt(tt)
            elif self.args.verbose:
                print("==> %s <==" % name)
                for t0, t1, txt in tt:
                    print("%s  %s" % (self.formattime(t0), txt))
            else:
                print("==> %s <==" % name)
                for t0, t1, txt in tt:
                    print(txt)

    @staticmethod
    def formattime(t):
        m = int(t/60) ; t -= 60*m
        h = int(m/60) ; m -= 60*h
        return "%d:%02d:%06.3f" % (h, m, t)

    @staticmethod
    def srttime(t):
        return formattime(t).replace('.', ',')

    @staticmethod
    def output_srt(tt):
        n = 1
        for t0, t1, txt in tt:
            print(n)
            print("%s --> %s" % (srttime(t0), srttime(t1)))
            print(txt)
            print()

    @staticmethod
    def unhtml(htmltext):
        """
        Removes html font tags, and decodes html entities
        """
        return html.unescape(re.sub(r'</?font[^>]*>', '', htmltext))

    def extracttext(self, xml):
        """
        Returns a list of tuples: time, endtime, text
        """
        lines = []
        tstart = None
        tend = None
        text = None
        def handle_begin_element(elem, attr):
            nonlocal text, tstart, tend
            if elem == 'text':
                text = ""
                tstart = float(attr.get('start'))
                tend = tstart + float(attr.get('dur'))

        def handle_end_element(elem):
            nonlocal text
            if elem == 'text':
                lines.append((tstart, tend, self.unhtml(text)))
                text = None
        def handle_data(data):
            nonlocal text
            if text is not None:
                text += data

        parser = ParserCreate()
        parser.StartElementHandler = handle_begin_element
        parser.EndElementHandler = handle_end_element
        parser.CharacterDataHandler = handle_data
        parser.Parse(xml, 1)

        return lines


class PlaylistReader:
    """
    class which can print a playlist's contents.
    """
    def __init__(self, args, yt, cfg):
        self.args = args
        self.yt = yt
        self.cfg = cfg

    def output(self):
        playlist = getitem(self.cfg, ("response",), "response", "contents", "twoColumnWatchNextResults", "playlist")
        if playlist:
            print("Title: %s" % getitem(playlist, "playlist", "title"))
            for entry in getitem(playlist, "playlist", "contents"):
                vid = getitem(entry, "playlistPanelVideoRenderer", "videoId")
                title = getitem(entry, "playlistPanelVideoRenderer", "title", "simpleText")
                print("%s - %s" % (vid, title))
            return
        playlist = getitem(self.cfg, ("response",), "response", "contents", "twoColumnBrowseResultsRenderer", "tabs", 0, "tabRenderer", "content", "sectionListRenderer", "contents", 0, "itemSectionRenderer", "contents", 0, "playlistVideoListRenderer")
        if playlist:
            for entry in playlist["contents"]:
                vid = getitem(entry, "playlistVideoRenderer", "videoId")
                title = getitem(entry, "playlistVideoRenderer", "title", "simpleText")
                print("%s - %s" % (vid, title))
            cont = self.getcontinuation(playlist)
            print("cont=", cont)
            while cont:
                browsejson = self.yt.browse(cont)
                if self.args.debug:
                    print("============ browse req")
                    print(browsejson.decode('utf-8'))
                    print()


                js = json.loads(browsejson)

                playlist = getitem(js, ("response",), "response", "continuationContents", "gridContinuation")
                if playlist:
                    for entry in getitem(playlist, "items"):
                        vid = getitem(entry, "gridVideoRenderer", "videoId")
                        title = getitem(entry, "gridVideoRenderer", "title", "simpleText")
                        print("%s - %s" % (vid, title))
                playlist = getitem(js, ("response",), "response", "continuationContents", "playlistVideoListContinuation")
                if playlist:
                    for entry in getitem(playlist, "contents"):
                        vid = getitem(entry, "playlistVideoRenderer", "videoId")
                        title = getitem(entry, "playlistVideoRenderer", "title", "simpleText")
                        print("%s - %s" % (vid, title))

                cont = self.getcontinuation(playlist)


            return

    def getcontinuation(self, p):
        p = getitem(p, "continuations", 0, "nextContinuationData")
        if not p:
            return
        return p["continuation"], p["clickTrackingParams"]




def main():
    import argparse
    parser = argparse.ArgumentParser(description='Extract Youtube comments')
    parser.add_argument('--debug', '-d', action='store_true', help='print all intermediate steps')
    parser.add_argument('--verbose', '-v', action='store_true', help='prefix each line with the timestamp')
    parser.add_argument('--comments', '-c', action='store_true', help='Print video comments')
    parser.add_argument('--subtitles', '-t', action='store_true', help='Print video comments')
    parser.add_argument('--playlist', '-l', action='store_true', help='Print playlist items')
    parser.add_argument('--srt', action='store_true', help='Output subtitles in .srt format.')
    parser.add_argument('yturl', type=str)
    args = parser.parse_args()

    yt = Youtube(args)
    cfg = yt.getpageinfo(args.yturl)

    if args.comments:
        cmt = CommentReader(args, yt, cfg)
        cmt.recursecomments()
    elif args.subtitles:
        txt = SubtitleReader(args, yt, cfg)
        txt.output()
    elif args.playlist:
        lst = PlaylistReader(args, yt, cfg)
        lst.output()
        pass
    else:
        print("nothing to do")

   
if __name__ == '__main__':
    main()

