import time
import renpy.display

from renpy.display.textsupport import \
    TAG, TEXT, PARAGRAPH, DISPLAYABLE

import renpy.display.textsupport as textsupport
import renpy.display.texwrap as texwrap
import renpy.display.ftfont as ftfont

import time
import contextlib

try:
    from _renpybidi import log2vis, WRTL, RTL, ON
except:
    pass


@contextlib.contextmanager
def timed(name):
    start = time.time()
    yield
    print name, (time.time() - start) * 1000.0, "ms"


ftfont.init()

# TODO: Move fonts over to their own file.
font_cache = { }
font_face_cache = { }

def get_font(font, size, bold, italic, outline, antialias):
    key = (font, size, bold, italic, outline, antialias)

    rv = font_cache.get(key, None)    
    if rv is not None:
        return rv
    
    face = font_face_cache.get(font, None)
    if face is None:
        face = ftfont.FTFace(renpy.loader.load(font), 0)
        font_face_cache[font] = face
        
        
    rv = ftfont.FTFont(face, size, bold, italic, outline, antialias)
    font_cache[key] = rv
    
    return rv
    

class Blit(object):
    """
    Represents a blit command, which can be used to render a texture to a 
    render. This is a rectangle with an associated alpha.
    """
    
    def __init__(self, x, y, w, h, alpha=1.0):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.alpha = alpha

    def __repr__(self):
        return "<Blit ({}, {}, {}, {}) {}>".format(self.x, self.y, self.w, self.h, self.alpha)

        
def outline_blits(blits, outline):
    """
    Given a list of blits, adjusts it for the given outline size. That means 
    adding borders on the left and right of each line of blits. Returns a second
    list of blit objects.
    
    We assume that there are a discrete set of vertical areas that divide the 
    original blits, and that no blit covers two vertical areas. So something
    like:
    
     _____________________________________
    |_____________________________________|
    |___________|_________________|_______|
    |_____________________|_______________|
    
    is fine, but:
    
     _____________________________________
     |              |_____________________|
     |______________|_____________________|
     
    is forbidden. That's an invariant that the blit_<method> functions are
    required to enforce.    
    """
    
    # Sort the blits.
    blits.sort(key=lambda b : (b.y, b.x))
    
    # The y coordinate that everything in the current line shares. This can 
    # be adjusted in the output blits.
    line_y = 0
    
    # The y coordinate of the top of the current line.
    top_y = 0
    
    # The y coordinate of the bottom of the current line.
    bottom_y = 0


    # The maximum x coordinate of the previous blit on this line.
    max_x = 0
    
    rv = [ ]
    
    for b in blits:

        x0 = b.x
        x1 = b.x + b.w + outline * 2
        
        y0 = b.y
        y1 = b.y + b.h + outline * 2
    
        if line_y != y0:
            line_y = y0
            top_y = bottom_y
            max_x = 0

        y0 = top_y
            
        if y1 > bottom_y:
            bottom_y = y1
        
        if max_x > x0:
            x0 = max_x
            
        max_x = x1
        
        rv.append(Blit(x0, y0, x1 - x0, y1 - y0, b.alpha))
        
    return rv
    

class DrawInfo(object):
    """
    This object is supplied as a parameter to the draw method of the various
    segments. It has the following fields:
    
    `surface`
        The surface to draw to.
        
    `override_color`
        If not None, a color that's used for this outline/shadow. 
        
    `outline`
        The amount to outline the text by.
    
    `displayable_blits`
        If not none, this is a list of (displayable, xo, yo) tuples. The draw
        method adds displayable blits to this list when this is not None.
    """
    
    # No implementation, this is set up in the layout object.


class TextSegment(object):
    """
    This represents a segment of text that has a single set of properties
    applied to it.
    """
    
    def __init__(self, source=None):
        """
        Creates a new segment of text. If `source` is given, this starts off
        a copy of that source segment. Otherwise, it's up to the code that 
        creates it to initialize it with defaults.
        """
            
        if source is not None:
            self.antialias = source.antialias
            self.font = source.font
            self.size = source.size
            self.bold = source.bold
            self.italic = source.italic
            self.underline = source.underline
            self.strikethrough = source.strikethrough
            self.color = source.color
            self.black_color = source.black_color
            self.hyperlink = source.hyperlink
            self.kerning = source.kerning
            self.cps = source.cps
            self.ruby_top = source.ruby_top
            self.ruby_bottom = source.ruby_bottom

        else:
            self.hyperlink = 0
            self.cps = 0
            self.ruby_top = False
            self.ruby_bottom = False
            
    def __repr__(self):
        return "<TextSegment font={font}, size={size}, bold={bold}, italic={italic}, underline={underline}, color={color}, black_color={black_color}, hyperlink={hyperlink}>".format(**self.__dict__)
            
    def take_style(self, style):
        """
        Takes the style of this text segement from the named style object.
        """
        
        self.antialias = style.antialias
        self.font = style.font
        self.size = style.size
        self.bold = style.bold
        self.italic = style.italic
        self.underline = style.underline
        self.strikethrough = style.strikethrough
        self.color = style.color
        self.black_color = style.black_color
        self.hyperlink = None
        self.kerning = style.kerning
        
        if style.slow_cps is True:
            self.cps = renpy.game.preferences.text_cps
            
        self.cps = self.cps * style.slow_cps_multiplier

    # From here down is the public glyph API.

    def glyphs(self, s):
        """
        Return the list of glyphs corresponding to unicode string s.
        """

        fo = get_font(self.font, self.size, self.bold, self.italic, 0, self.antialias)
        rv = fo.glyphs(s)
        
        # Apply kerning to the glyphs.
        if self.kerning:
            textsupport.kerning(rv, self.kerning)
        
        if self.hyperlink:
            for g in rv:
                g.hyperlink = self.hyperlink
        
        if self.ruby_bottom:
            textsupport.mark_ruby_bottom(rv)
        elif self.ruby_top:
            textsupport.mark_ruby_top(rv)
        
        return rv

    def draw(self, glyphs, di):
        """
        Draws the glyphs to surf.
        """
        
        if di.override_color:
            color = di.override_color
        else:
            color = self.color
        
        fo = get_font(self.font, self.size, self.bold, self.italic, di.outline, self.antialias)
        fo.draw(di.surface, 0, 0, color, glyphs, self.underline, self.strikethrough)

    def assign_times(self, gt, glyphs):
        """
        Assigns times to the glyphs. `gt` is the starting time of the first
        glyph, and it returns the starting time of the first glyph in the next
        segment.
        """
        
        return textsupport.assign_times(gt, self.cps, glyphs)



class SpaceSegment(object):
    """
    A segment that's used to render horizontal or vertical whitespace.
    """
    
    def __init__(self, ts, width=0, height=0):
        """
        `ts`
            The text segment that this SpaceSegment follows.
        """
        
        self.glyph = glyph = textsupport.Glyph()

        glyph.character = 0
        glyph.ascent = 0
        glyph.line_spacing = height
        glyph.advance = width
        glyph.width = width
        
        if ts.hyperlink:
            glyph.hyperlink = ts.hyperlink
        
        self.cps = ts.cps
        
    def glyphs(self, s):
        return [ self.glyph ]
    
    def draw(self, glyphs, di):
        # Does nothing - since there's nothing to draw.        
        return
        
    def assign_times(self, gt, glyphs):
        if self.cps != 0:
            gt += 1.0 / self.cps
        
        self.glyph.time = gt
        return gt


class DisplayableSegment(object):
    """
    A segment that's used to render horizontal or vertical whitespace.
    """
    
    def __init__(self, ts, d, renders):
        """
        `ts`
            The text segment that this SpaceSegment follows.
        """
        
        self.d = d
        rend = renders[d]
        
        w, h = rend.get_size()
        
        self.glyph = glyph = textsupport.Glyph()

        glyph.character = 0
        glyph.ascent = 0
        glyph.line_spacing = h
        glyph.advance = w
        glyph.width = w
        
        if ts.hyperlink:
            glyph.hyperlink = ts.hyperlink
        
        self.cps = ts.cps
        
    def glyphs(self, s):
        return [ self.glyph ]
    
    def draw(self, glyphs, di):
        if di.displayable_blits is not None:
            di.displayable_blits.append((self.d, self.glyph.x, self.glyph.y, self.glyph.time))
        
    def assign_times(self, gt, glyphs):
        if self.cps != 0:
            gt += 1.0 / self.cps
        
        self.glyph.time = gt
        return gt

    
class Layout(object):
    """
    Represents the layout of text.
    """

    def __init__(self, text, width, height, renders):
        """
        `text` 
            The text object this layout is associated with.
        `width`, `height` 
            The height of the laid-out text.
        """
        
        style = text.style
                
        # Do we have any hyperlinks in this text? Set by segment.
        self.has_hyperlinks = False

        # Do we have any ruby in the text?
        self.has_ruby = False
                
        # Slow text that is not before the start segment is displayed
        # instantaneously. Text after the end segment is not displayed
        # at all. These are controlled by the {_start} and {_end} tags.
        self.start_segment = None
        self.end_segment = None

        self.width = width
        self.height = height

        # Figure out outlines and other info.
        outlines, xborder, yborder, xoffset, yoffset = self.figure_outlines(style)        
        self.outlines = outlines
        self.xborder = xborder
        self.yborder = yborder
        self.xoffset = xoffset
        self.yoffset = yoffset
        
        # Adjust the borders by the outlines.                
        width -= self.xborder
        height -= self.yborder

        # The greatest x coordinate of the text.       
        maxx = 0
        
        # The current y, which becomes the maximum height once all paragraphs
        # have been rendered.
        y = 0

        # A list of glyphs - all the glyphs we know of.
        all_glyphs = [ ]

        # A list of (segment, glyph_list) pairs for all paragraphs.
        par_seg_glyphs = [ ]

        # A list of Line objects.
        lines = [ ]

        # The time at which the next glyph will be displayed.
        gt = 0.0

        # 2. Breaks the text into a list of paragraphs, where each paragraph is 
        # represented as a list of (Segment, text string) tuples. 
        #
        # This takes information from the various styles that apply to thr text,
        # and so needs to be redone when the style of the text changes.
        self.paragraphs = self.segment(text.tokens, style, renders)
      
        for p in self.paragraphs:

            # TODO: RTL - apply RTL to the text of each segment, then 
            # reverse the order of the segments in each paragraph.
            
            if renpy.config.rtl:            
                p, rtl = self.rtl_paragraph(p)
            else:
                rtl = False
                    
            # 3. Convert each paragraph into a Segment, glyph list. (Store this
            # to use when we draw things.)
            
            # A list of glyphs in the line.
            line_glyphs = [ ]
            
            # A list of (segment, list of glyph) pairs.
            seg_glyphs = [ ]

            for ts, s in p:
                glyphs = ts.glyphs(s)

                t = (ts, glyphs)                
                seg_glyphs.append(t)
                par_seg_glyphs.append(t)
                line_glyphs.extend(glyphs)
                all_glyphs.extend(glyphs)

            # TODO: RTL - Reverse each line, segment, so that we can use LTR
            # linebreaking algorithms.
            if rtl:
                line_glyphs.reverse()
                for ts, glyphs in seg_glyphs:
                    glyphs.reverse()
            
            # Tag the glyphs that are eligible for line breaking, and if
            # they should be included or excluded from the end of a line.
            language = style.language
            
            if language == "unicode" or language == "eastasian":
                textsupport.annotate_unicode(line_glyphs, False)
            elif language == "korean-with-spaces":
                textsupport.annotate_unicode(line_glyphs, True)
            elif language == "western":
                textsupport.annotate_western(line_glyphs)
            else:
                raise Exception("Unknown language: {0}".format(language))

            # Break the paragraph up into lines.                    
            layout = style.layout

            if layout == "tex":                
                texwrap.linebreak_tex(line_glyphs, width - style.first_indent, width - style.rest_indent, False)
            elif layout == "subtitle" or layout == "tex-subtitle":
                texwrap.linebreak_tex(line_glyphs, width - style.first_indent, width - style.rest_indent, True)            
            elif layout == "greedy":
                textsupport.linebreak_greedy(line_glyphs, width - style.first_indent, width - style.rest_indent)
            elif layout == "nobreak":
                textsupport.linebreak_nobreak(line_glyphs)
            else:
                raise Exception("Unknown layout: {0}".format(layout))
                        
            for ts, glyphs in seg_glyphs:                
                # Only assign a time if we're past the start segment.
                if self.start_segment is not None:
                    if self.start_segment is ts:
                        self.start_segment = None
                    else:
                        continue

                # A hack to prevent things past the end segment from displaying.
                if ts is self.end_segment:
                    gt += 10000000000
                
                gt = ts.assign_times(gt, glyphs)
                                
            # RTL - Reverse the glyphs in each line, back to RTL order,
            # now that we have lines. 
            if rtl:
                line_glyphs = textsupport.reverse_lines(line_glyphs)
                        
            # Taking into account indentation, kerning, justification, and text_align,
            # lay out the X coordinate of each glyph.
            
            w = textsupport.place_horizontal(line_glyphs, 0, style.first_indent, style.rest_indent)
            if w > maxx:
                maxx = w
           
            # Figure out the line height, line spacing, and the y coordinate of each
            # glyph. 
            l, y = textsupport.place_vertical(line_glyphs, y, style.line_spacing, style.line_leading)
            lines.extend(l)

        if style.min_width > maxx + self.xborder:
            maxx = style.min_width - self.xborder
            
        # Figure out the size of the texture. (This is a little over-sized,
        # but it simplifies the code to not have to care about borders on a 
        # per-outline basis.)
        sw, sh = size = (maxx + self.xborder, y + self.yborder)
        self.size = size

        textsupport.align_and_justify(lines, maxx, style.text_align, style.justify)

        if self.has_ruby:
            textsupport.place_ruby(all_glyphs, style.ruby_style.xoffset, sw, sh)
        
        # A map from (outline, color) to a texture.
        self.textures = { }

        di = DrawInfo()

        for o, color, _xo, _yo in self.outlines:
            key = (o, color)
            
            if key in self.textures:
                continue
            
            # Create the texture.
            surf = renpy.display.pgrender.surface(size, True)
            
            di.surface = surf
            di.override_color = color
            di.outline = o
                
            if color == None:
                self.displayable_blits = [ ]
                di.displayable_blits = self.displayable_blits
            else:
                di.displayable_blits = None
            
            for ts, glyphs in par_seg_glyphs:
                ts.draw(glyphs, di)
    
            with timed("texture load"):
                renpy.display.draw.mutated_surface(surf)
                tex = renpy.display.draw.load_texture(surf)
    
            self.textures[key] = tex
        
        # Compute the max time for all lines, and the max max time.
        self.max_time = textsupport.max_times(lines)
        
        # Store the lines, so we have them for typeout.
        self.lines = lines
        
        # Store the hyperlinks, if any.
        if self.has_hyperlinks:
            self.hyperlinks = textsupport.hyperlink_areas(lines)
        else:
            self.hyperlinks = [ ]
        
        # TODO: Log an overflow if the laid out width or height is larger than the
        # size of the provided area.
        
        
    def segment(self, tokens, style, renders):
        """
        Breaks the text up into segments. This creates a list of paragraphs,
        which each paragraph being represented as a list of TextSegment, glyph
        list tuples.
        """
        
        # A map from an integer to the number of the hyperlink this segment 
        # is part of.
        self.hyperlink_targets = { }
        
        paragraphs = [ ]
        line = [ ]

        ts = TextSegment(None) 

        ts.cps = style.slow_cps
        if ts.cps is None or ts.cps is True:
            ts.cps = renpy.game.preferences.text_cps
        
        ts.take_style(style)
                
        # The text segement stack.
        tss = [ ts ]

        def push():
            """
            Creates a new text segment, and pushes it onto the text segement
            stack. Returns the new text segment.
            """
            
            ts = TextSegment(tss[-1])
            tss.append(ts)
            
            return ts
                
        for type, text in tokens:
            
            if type == PARAGRAPH:
                
                # Note that this code is duplicated for the p tag, below.
                if not line:
                    line.append((tss[-1], u" "))
                
                paragraphs.append(line)
                line = [ ]
                
                continue
                
            elif type == TEXT:
                line.append((tss[-1], text))
                continue
            
            elif type == DISPLAYABLE:
                line.append((DisplayableSegment(tss[-1], text, renders), u""))
                continue
            
            # Otherwise, we have a text tag.
            
            tag, _, value = text.partition("=")
            
            if tag and tag[0] == "/":
                tss.pop()
                
                if not tss:                
                    raise Exception("%r closes a text tag that isn't open." % text)
            
            elif tag == "_start":
                ts = push()
                tss.pop(-2)
                self.start_segment = ts
                
            elif tag == "_end":
                ts = push()
                tss.pop(-2)
                self.end_segment = ts
                
            elif tag == "p":
                # Duplicated from the newline tag.
                
                if not line:
                    line.append((ts[-1], " "))
                
                paragraphs.append(line)
                line = [ ]

            elif tag == "space":
                width = int(value)                
                line.append((SpaceSegment(tss[-1], width=width), ""))

            elif tag == "vspace":
                # Duplicates from the newline tag.
                
                height = int(value)                

                if line:
                    paragraphs.append(line)

                line = [ (SpaceSegment(tss[-1], height=height), "") ]
                paragraphs.append(line)
                
                line = [ ]

            elif tag == "w":
                pass
            
            elif tag == "fast":
                pass
            
            elif tag == "nw":
                pass
            
            elif tag == "a":
                self.has_hyperlinks = True
                
                hyperlink_styler = style.hyperlink_functions[0]
                    
                if hyperlink_styler:                                        
                    hls = hyperlink_styler(value)
                else:
                    hls = style

                old_prefix = hls.prefix

                link = len(self.hyperlink_targets) + 1
                self.hyperlink_targets[link] = value

                if renpy.display.focus.argument == link:
                    hls.set_prefix("hover_")
                else:
                    hls.set_prefix("idle_")

                ts = push()
                ts.take_style(hls)
                ts.hyperlink = link

                hls.set_prefix(old_prefix)
 
            elif tag == "b":
                push().bold = True
                
            elif tag == "i":
                push().italic = True

            elif tag == "u":
                push().underline = True
                
            elif tag == "s":
                push().strikethrough = True
                
            elif tag == "plain":
                ts = push()
                ts.bold = False
                ts.italic = False
                ts.underline = False
                ts.strikethrough = False
                
            elif tag == "":
                style = getattr(renpy.store.style, value)
                push().take_style(style)
                
            elif tag == "font":
                push().font = value
                
            elif tag == "size":
                if value[0] in "+-":
                    push().size += int(value)
                else:
                    push().size = int(value)
                    
            elif tag == "color":
                push().color = renpy.easy.color(value)
                
            elif tag == "k":
                push().kerning = float(value)
            
            elif tag == "rt":
                ts = push()
                ts.take_style(style.ruby_style)
                ts.ruby_top = True
                self.has_ruby = True
                
            elif tag == "rb":
                push().ruby_bottom = True
                # We only care about ruby if we have a top.
                
            elif tag == "cps":
                ts = push()
                
                if value[0] == "*":
                    ts.cps *= float(value[1:])
                else:
                    ts.cps = float(value)
            
            else:
                raise Exception("Unknown text tag %r" % text)
            
        if not line:
            line.append((ts, ""))
                
        paragraphs.append(line)

        return paragraphs

    def rtl_paragraph(self, p):
        """
        Given a paragraph (a list of segment, text tuples) handles 
        RTL and ligaturization. This returns the reversed RTL paragraph, 
        which differers from the LTR one. It also returns a flag that is 
        True if this is an rtl paragraph.
        """
        
        direction = ON
        
        l = [ ]
        
        for ts, s in p:
            s, direction = log2vis(s, direction)
            l.append((ts, s))
            
        rtl = (direction == RTL or direction == WRTL)

        return l, rtl


    def figure_outlines(self, style):
        """
        Return a list containing the outlines, including an outline
        representing the drop shadow, if we have one, also including
        an entry for the main text, with color None. Also returns the 
        space reserved for outlines - to be deducted from the width
        and the height.
        """
        
        style_outlines = style.outlines
        dslist = style.drop_shadow

        if not style_outlines and not dslist:
            return [ (0, None, 0, 0) ], 0, 0, 0, 0
                
        outlines = [ ]
                
        if dslist:
            if not isinstance(dslist, list):                
                dslist = [ dslist ]
                        
            for dsx, dsy in dslist:
                outlines.append((0, style.drop_shadow_color, dsx, dsy))
                
        outlines.extend(style_outlines)
        
        # The outline borders we reserve.
        left = 0
        right = 0
        top = 0
        bottom = 0
                
        for o, _c, x, y in outlines:
            
            l = x - o 
            r = x + o
            t = y - o
            b = y + o
            
            if l < left:
                left = l
                
            if r > right:
                right = r
                
            if t < top:
                top = t
                
            if b > bottom:
                bottom = b
                
        outlines.append((0, None, 0, 0))
        
        return outlines, right - left, bottom - top, -left, -top
        

    def blits_typewriter(self, st):
        """
        Given a st and an outline, returns a list of blit objects that 
        can be used to blit those objects.
        """
        
        width, _height = self.size
        
        rv = [ ]
        
        max_y = 0
        
        for l in self.lines:
            
            if l.max_time > st:
                break
            
            max_y = l.y + l.height
            
        else:
            l = None
            
        if max_y:
            rv.append(Blit(0, 0, width, max_y))

        if l is None:
            return rv
            
        # If l is not none, then we have a line for which max_time has not 
        # yet been reached. Blit it.

        min_x = width 
        max_x = 0

        for g in l.glyphs:
            
            if g.time > st:
                continue
            
            if g.x + g.advance > max_x:
                max_x = g.x + g.advance
                
            if g.x  < min_x:
                min_x = g.x
                
        if min_x < max_x:
            rv.append(Blit(min_x, l.y, max_x - min_x, l.height))
            
        return rv
        
    def redraw_typewriter(self, st):
        """
        Return the time of the first glyph that should be shown after st.
        """
        
        for l in self.lines:
            if not l.glyphs:
                continue
            
            if l.max_time > st:
                break

        else:
            return None
        
        return min(i.time for i in l.glyphs if i.time > st) - st

layout_cache_old = { }
layout_cache_new = { }

def layout_cache_clear():
    """
    Clears the old and new layout caches.
    """
    
    global layout_cache_old, layout_cache_new
    layout_cache_old = { }
    layout_cache_new = { }
    
def layout_cache_tick():
    """
    Called once per interaction, to merge the old and new layout caches.
    """
    
    global layout_cache_old, layout_cache_new
    layout_cache_old = layout_cache_new
    layout_cache_new = { }
    
class NewText(renpy.display.core.Displayable):
    
    def __init__(self, text, slow=None, replaces=None, scope=None, substitute=True, **properties):
                
        super(NewText, self).__init__(**properties)
        
        # We need text to be a list, so if it's not, wrap it.   
        if not isinstance(text, list):
            text = [ text ]

        # A list of text and displayables we're showing.                
        self.text = text
                           
        # If slow is None, the style decides if we're in slow text mode.
        if slow is None and self.style.slow_cps:
            slow = True

        if renpy.game.less_updates:
            slow = False
        
        # True if we're using slow text mode.
        self.slow = slow

        # The scope substitutions are performed in, in addition to renpy.store.
        self.scope = scope

        # Should substitutions be done?
        self.substitute = substitute

        # Call update to retokenize.
        self.update()


    def update(self):
        """
        This needs to be called after text has been updated, but before
        any layout objects are created.
        """
        
        text = [ ]
        
        # Perform substitution as necessary.
        for i in self.text:
            if isinstance(i, basestring):
                if self.substitute:
                    i = renpy.substitutions.substitute(i, self.scope)
                
                i = unicode(i)
                
            text.append(i)
        
        tokens = self.tokenize(text)
        
        # self.tokens is a list of pairs, where the first component of 
        # each pair is TEXT, NEWLINE, TAG, or DISPLAYABLE, and the second 
        # is text or a displayable.
        # 
        # self.displayables is the set of displayables used by this 
        # Text.        
        self.tokens, self.displayables = self.get_displayables(tokens)

        for i in self.displayables:
            i.per_interact()


    def kill_layout(self):
        """
        Kills the layout of this Text. Used when the text or style
        changes.
        """

        key = id(self)        
        layout_cache_old.pop(key, None)
        layout_cache_new.pop(key, None)
    
    def get_layout(self):
        """
        Gets the layout of this Text, creating a new layout object if
        none exists.
        """

        key = id(self)
        
        rv = layout_cache_new.get(key, None)
        
        if rv is None:
            rv = layout_cache_old.get(key, None)
            
        return rv
        
    def focus(self, default=False):
        """
        Called when a hyperlink gains focus.
        """

        self.kill_layout()
        renpy.display.render.redraw(self, 0)

        hyperlink_focus = self.style.hyperlink_functions[2]
        target = self.layout.hyperlink_targets.get(renpy.display.focus.argument, None)

        if hyperlink_focus:
            return hyperlink_focus(target)

    def unfocus(self, default=False):
        """
        Called when a hyperlink loses focus, or isn't focused to begin with.
        """

        self.kill_layout()
        renpy.display.render.redraw(self, 0)            

        hyperlink_focus = self.style.hyperlink_functions[2]

        if hyperlink_focus:
            return hyperlink_focus(None)
        
    def event(self, ev, x, y, st):
        """
        Space, Enter, or Click ends slow, if it's enabled.
        """
        
        if self.slow and self.style.slow_abortable and renpy.display.behavior.map_event(ev, "dismiss"):
            # self.call_slow_done(st)
            self.slow = False
            raise renpy.display.core.IgnoreEvent()
        
        layout = self.get_layout()
        if layout is None:
            return
        
        for d, xo, yo, _ in layout.displayable_blits:
            rv = d.event(ev, x - xo - layout.xoffset, y - yo - layout.yoffset, st)
            if rv is not None:
                return rv

        if (self.is_focused() and
            renpy.display.behavior.map_event(ev, "button_select")):

            clicked = self.style.hyperlink_functions[1]

            if clicked is not None: 
                target = layout.hyperlink_targets.get(renpy.display.focus.argument, None)
                
                rv = self.style.hyperlink_functions[1](target)
                return rv

    def render(self, width, height, st, at):

        start = time.time()

        # Render all of the child displayables.
        renders = { }

        for i in self.displayables:
            renders[i] = renpy.display.render.render(i, width, height, st, at)
        
        # Find the layout, and update to the new size and width if necessary.
        layout = self.get_layout()

        if layout is None or layout.width != width or layout.height != height:
            layout = Layout(self, width, height, renders)
            layout_cache_new[id(self)] = layout
        
        # The laid-out size of this Text.
        w, h = layout.size            
            
        # Get the list of blits we want to undertake.
        if not self.slow:
            blits = [ Blit(0, 0, w - layout.xborder, h - layout.yborder) ]
            redraw = None
        else:
            # TODO: Make this changeable.
            blits = layout.blits_typewriter(st)
            redraw = layout.redraw_typewriter(st)

        # Blit text layers.
        rv = renpy.display.render.Render(w, h)

        for o, color, xo, yo in layout.outlines:
            tex = layout.textures[o, color]
            
            if o:
                oblits = outline_blits(blits, o)            
            else:
                oblits = blits            
        
            for b in oblits:
            
                rv.blit(
                    tex.subsurface((b.x, b.y, b.w, b.h)),
                    (b.x + xo + layout.xoffset - o, b.y + yo + layout.yoffset - o))

        # Blit displayables.
        for d, xo, yo, t in layout.displayable_blits:

            if self.slow and t > st:
                continue
            
            rv.blit(renders[d], (xo + layout.xoffset, yo + layout.yoffset))

        # Add in the focus areas.
        for hyperlink, hx, hy, hw, hh in layout.hyperlinks:
            rv.add_focus(self, hyperlink, hx + layout.xoffset, hy + layout.yoffset, hw, hh)
        
        # Figure out if we need to redraw.
        if self.slow and redraw is not None:
            renpy.display.render.redraw(self, redraw)
        
        print "NEW", (time.time() - start) * 1000.0
        
        return rv
       
       
    def tokenize(self, text):
        """
        Convert the text into a list of tokens.
        """
        
        tokens = [ ]
        
        for i in text:

            if isinstance(i, unicode):
                tokens.extend(textsupport.tokenize(i))

            elif isinstance(i, str):
                tokens.extend(textsupport.tokenize(unicode(i)))
                
            elif isinstance(i, renpy.display.core.Displayable):
                tokens.append((DISPLAYABLE, i))
                
            else:
                raise Exception("Can't display {!r} as Text.".format(i))
                
        return tokens    
    

    def get_displayables(self, tokens):
        """
        Goes through the list of tokens. Returns the set of displayables that 
        we know about, and an updated list of tokens with all image tags turned
        into displayables.
        """
        
        displayables = set()        
        new_tokens = [ ]
        
        for t in tokens:
            
            kind, text = t
            
            if kind == DISPLAYABLE:
                displayables.add(text)
                new_tokens.append(t)
                continue
            
            if kind == TAG:
                tag, _, value = text.partition("=")
                
                if tag == "image":
                    d = renpy.easy.displayable(value)
                    displayables.add(d)                    
                    new_tokens.append((DISPLAYABLE, d))

                    continue
                    
            new_tokens.append(t)

        return new_tokens, displayables
    