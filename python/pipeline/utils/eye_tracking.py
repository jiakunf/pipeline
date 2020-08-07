from collections import defaultdict
from itertools import count

import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

from ..exceptions import PipelineException

try:
    import cv2
except ImportError:
    print("Could not find cv2. You won't be able to use the pupil tracker.")

ANALOG_PACKET_LEN = 2000


class CVROIGrabber:
    start = None
    end = None
    roi = None

    def __init__(self, img):
        self.img = img
        self.draw_img = np.asarray(img / img.max(), dtype=float)
        self.mask = 1 + 0 * img
        self.exit = False
        self.r = 40
        self.X, self.Y = np.mgrid[:img.shape[0], :img.shape[1]]

    def grab(self):
        print('Contrast (std)', np.std(self.img))
        img = np.asarray(self.img / self.img.max(), dtype=float)
        cv2.namedWindow('real image')
        cv2.setMouseCallback('real image', self, 0)

        while not self.exit:
            cv2.imshow('real image', img)
            if (cv2.waitKey(0) & 0xFF) == ord('q'):
                cv2.waitKey(1)
                cv2.destroyAllWindows()
                break
        cv2.waitKey(2)

    def __call__(self, event, x, y, flags, params):
        # img = np.asarray(self.img , dtype=np.uint8)[...,None] * np.ones((1,1,3), dtype=np.uint8)
        img = np.asarray(self.img / self.img.max(), dtype=float)
        cv2.imshow('real image', self.draw_img)

        if event == cv2.EVENT_LBUTTONDOWN:
            print('Start Mouse Position: ' + str(x) + ', ' + str(y))
            self.start = np.asarray([x, y])

        elif event == cv2.EVENT_LBUTTONUP:
            self.end = np.asarray([x, y])
            x = np.vstack((self.start, self.end))
            tmp = np.hstack((x.min(axis=0), x.max(axis=0)))
            roi = np.asarray([[tmp[1], tmp[3]], [tmp[0], tmp[2]]], dtype=int) + 1
            crop = img[roi[0, 0]:roi[0, 1], roi[1, 0]:roi[1, 1]]
            crop = np.asarray(crop / crop.max(), dtype=float)
            self.roi = roi
            cv2.imshow('crop', crop)

            # m = (img * self.mask).copy() # needed for a weird reason
            self.draw_img = (img * self.mask).copy()
            cv2.rectangle(self.draw_img, tuple(self.start), tuple(self.end), (0, 255, 0), 2)

            cv2.imshow('real image', self.draw_img)
            key = (cv2.waitKey(0) & 0xFF)
            if key == ord('q'):
                cv2.destroyAllWindows()
                self.exit = True
            elif key == ord('c'):
                self.mask = 0 * self.mask + 1

        elif event == cv2.EVENT_MBUTTONDOWN:
            img = np.asarray(self.img / self.img.max(), dtype=float)

            self.mask[(self.X - y) ** 2 + (self.Y - x) ** 2 < self.r ** 2] = 0.
            self.draw_img[(self.X - y) ** 2 + (self.Y - x) ** 2 < self.r ** 2] = 0.
            cv2.imshow('real image', self.draw_img)

            key = (cv2.waitKey(0) & 0xFF)
            if key == ord('q'):
                cv2.destroyAllWindows()
                self.exit = True
            elif key == ord('c'):
                self.mask = 0 * self.mask + 1


class ROIGrabber:
    """
    Interactive matplotlib figure to grab an ROI from an image.

    Usage:

    rg = ROIGrabber(img)
    # select roi
    print(rg.roi) # get ROI
    """

    def __init__(self, img):
        plt.switch_backend('GTK3Agg')
        self.img = img
        self.start = None
        self.current = None
        self.end = None
        self.pressed = False
        self.fig, self.ax = plt.subplots(facecolor='w')

        self.fig.canvas.mpl_connect('button_press_event', self.on_press)
        self.fig.canvas.mpl_connect('button_release_event', self.on_release)
        self.fig.canvas.mpl_connect('motion_notify_event', self.on_move)
        self.replot()
        plt.show(block=True)

    def draw_rect(self, fr, to, color='dodgerblue'):
        x = np.vstack((fr, to))
        fr = x.min(axis=0)
        to = x.max(axis=0)
        self.ax.plot(fr[0] * np.ones(2), [fr[1], to[1]], color=color, lw=2)
        self.ax.plot(to[0] * np.ones(2), [fr[1], to[1]], color=color, lw=2)
        self.ax.plot([fr[0], to[0]], fr[1] * np.ones(2), color=color, lw=2)
        self.ax.plot([fr[0], to[0]], to[1] * np.ones(2), color=color, lw=2)
        self.ax.plot(fr[0], fr[1], 'ok', mfc='gold')
        self.ax.plot(to[0], to[1], 'ok', mfc='deeppink')

    def replot(self):
        self.ax.clear()
        self.ax.imshow(self.img, cmap=plt.cm.gray)

        if self.pressed:
            self.draw_rect(self.start, self.current, color='lime')
        elif self.start is not None and self.end is not None:
            self.draw_rect(self.start, self.current)
        self.ax.axis('tight')
        self.ax.set_aspect(1)
        self.ax.set_title('Close window when done', fontsize=16, fontweight='bold')
        plt.draw()

    @property
    def roi(self):
        x = np.vstack((self.start, self.end))
        tmp = np.hstack((x.min(axis=0), x.max(axis=0)))
        return np.asarray([[tmp[1], tmp[3]], [tmp[0], tmp[2]]], dtype=int) + 1

    def on_press(self, event):
        if event.xdata is not None and event.ydata is not None:
            self.pressed = True
            self.start = np.asarray([event.xdata, event.ydata])

    def on_release(self, event):
        if event.xdata is not None and event.ydata is not None:
            self.end = np.asarray([event.xdata, event.ydata])
        else:
            self.end = self.current
        self.pressed = False
        self.replot()

    def on_move(self, event):
        if event.xdata is not None and event.ydata is not None:
            self.current = np.asarray([event.xdata, event.ydata])
            if self.pressed:
                self.replot()


class PupilTracker:
    """
    Parameters:

    perc_high                    : float        # upper percentile for bright pixels
    perc_low                     : float        # lower percentile for dark pixels
    perc_weight                  : float        # threshold will be perc_weight*perc_low + (1- perc_weight)*perc_high
    relative_area_threshold      : float        # enclosing rotating rectangle has to have at least that amount of area
    ratio_threshold              : float        # ratio of major and minor radius cannot be larger than this
    error_threshold              : float        # threshold on the RMSE of the ellipse fit
    min_contour_len              : int          # minimal required contour length (must be at least 5)
    margin                       : float        # relative margin the pupil center should not be in
    contrast_threshold           : float        # contrast below that threshold are considered dark
    speed_threshold              : float        # eye center can at most move that fraction of the roi between frames
    dr_threshold                 : float        # maximally allow relative change in radius

    """

    def __init__(self, param, mask=None):
        self._params = param
        self._center = None
        self._radius = None
        self._mask = mask
        self._last_detection = 1
        self._last_ellipse = None

    @staticmethod
    def goodness_of_fit(contour, ellipse):
        center, size, angle = ellipse
        angle *= np.pi / 180
        err = 0
        for coord in contour.squeeze().astype(np.float):
            posx = (coord[0] - center[0]) * np.cos(-angle) - (coord[1] - center[1]) * np.sin(-angle)
            posy = (coord[0] - center[0]) * np.sin(-angle) + (coord[1] - center[1]) * np.cos(-angle)
            err += ((posx / size[0]) ** 2 + (posy / size[1]) ** 2 - 0.25) ** 2

        return np.sqrt(err / len(contour))

    @staticmethod
    def restrict_to_long_axis(contour, ellipse, corridor):
        center, size, angle = ellipse
        angle *= np.pi / 180
        R = np.asarray([[np.cos(-angle), - np.sin(-angle)], [np.sin(-angle), np.cos(-angle)]])
        contour = np.dot(contour.squeeze() - center, R.T)
        contour = contour[np.abs(contour[:, 0]) < corridor * ellipse[1][1] / 2]
        return (np.dot(contour, R) + center).astype(np.int32)

    def get_pupil_from_contours(self, contours, small_gray, mask, show_matching=5):
        ratio_thres = self._params['ratio_threshold']
        area_threshold = self._params['relative_area_threshold']
        error_threshold = self._params['error_threshold']
        min_contour = self._params['min_contour_len']
        margin = self._params['margin']
        speed_thres = self._params['speed_threshold']
        dr_thres = self._params['dr_threshold']
        err = np.inf
        best_ellipse = None
        best_contour = None
        kernel = np.ones((3, 3))

        results, cond = defaultdict(list), defaultdict(list)
        for j, cnt in enumerate(contours):

            mask2 = cv2.erode(mask, kernel, iterations=1)
            idx = mask2[cnt[..., 1], cnt[..., 0]] > 0
            cnt = cnt[idx]

            if len(cnt) < min_contour:  # otherwise fitEllipse won't work
                continue

            ellipse = cv2.fitEllipse(cnt)
            ((x, y), axes, angle) = ellipse
            if min(axes) == 0:  # otherwise ratio won't work
                continue
            ratio = max(axes) / min(axes)
            area = np.prod(ellipse[1]) / np.prod(small_gray.shape)
            curr_err = self.goodness_of_fit(cnt, ellipse)

            results['ratio'].append(ratio)
            results['area'].append(area)
            results['rmse'].append(curr_err)
            results['x coord'].append(x / small_gray.shape[1])
            results['y coord'].append(y / small_gray.shape[0])

            center = np.array([x / small_gray.shape[1], y / small_gray.shape[0]])
            r = max(axes)

            dr = 0 if self._radius is None else np.abs(r - self._radius) / self._radius
            dx = 0 if self._center is None else np.sqrt(np.sum((center - self._center) ** 2))

            results['dx'].append(dx)
            results['dr/r'].append(dr)
            matching_conditions = 1 * (ratio <= ratio_thres) + 1 * (area >= area_threshold) \
                                  + 1 * (curr_err < error_threshold) \
                                  + 1 * (margin < center[0] < 1 - margin) \
                                  + 1 * (margin < center[1] < 1 - margin) \
                                  + 1 * (dx < speed_thres * self._last_detection) \
                                  + 1 * (dr < dr_thres * self._last_detection)
            cond['ratio'].append(ratio <= ratio_thres)
            cond['area'].append(area >= area_threshold)
            cond['rmse'].append(curr_err < error_threshold)
            cond['x coord'].append(margin < center[0] < 1 - margin)
            cond['y coord'].append(margin < center[1] < 1 - margin)
            cond['dx'].append(dx < speed_thres * self._last_detection)
            cond['dr/r'].append(dr < dr_thres * self._last_detection)

            results['conditions'] = matching_conditions
            cond['conditions'].append(True)

            if curr_err < err and matching_conditions == 7:
                best_ellipse = ellipse
                best_contour = cnt
                err = curr_err
                cv2.ellipse(small_gray, ellipse, (0, 0, 255), 2)
            elif matching_conditions >= show_matching:
                cv2.ellipse(small_gray, ellipse, (255, 0, 0), 2)

        if best_ellipse is None:
            df = pd.DataFrame(results)
            df2 = pd.DataFrame(cond)

            print('-', end="", flush=True)
            if 'conditions' in df.columns and np.any(df['conditions'] >= show_matching):
                idx = df['conditions'] >= show_matching
                df = df[idx]
                df2 = df2[idx]
                df[df2] = np.nan
                print("\n", df, flush=True)
            self._last_detection += 1
        else:
            self._last_detection = 1

        return best_contour, best_ellipse

    _running_avg = None

    def preprocess_image(self, frame, eye_roi):
        h = int(self._params['gaussian_blur'])
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        img_std = np.std(gray)

        small_gray = gray[slice(*eye_roi[0]), slice(*eye_roi[1])]

        # Manual meso settins
        if 'extreme_meso' in self._params and self._params['extreme_meso']:
            c = self._params['running_avg']
            p = self._params['exponent']
            if self._running_avg is None:
                self._running_avg = np.array(small_gray / 255) ** p * 255
            else:
                self._running_avg = c * np.array(small_gray / 255) ** p * 255 + (1 - c) * self._running_avg
                small_gray = self._running_avg.astype(np.uint8)
                cv2.imshow('power', small_gray)
                # small_gray += self._running_avg.astype(np.uint8) - small_gray  # big hack
        # --- mesosetting end

        blur = cv2.GaussianBlur(small_gray, (2 * h + 1, 2 * h + 1), 0)  # play with blur

        _, thres = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return gray, small_gray, img_std, thres, blur

    @staticmethod
    def display(gray, blur, thres, eye_roi, fr_count, n_frames, ncontours=0, contour=None, ellipse=None,
                eye_center=None,
                font=cv2.FONT_HERSHEY_SIMPLEX):
        cv2.imshow('blur', blur)

        cv2.imshow('threshold', thres)
        cv2.putText(gray, "Frames {fr_count}/{frames} | Found contours {ncontours}".format(fr_count=fr_count,
                                                                                           frames=n_frames,
                                                                                           ncontours=ncontours),
                    (10, 30), font, 1, (255, 255, 255), 2)
        # cv.drawContours(mask, contours, -1, (255), 1)
        if contour is not None and ellipse is not None and eye_center is not None:
            ellipse = list(ellipse)
            ellipse[0] = tuple(eye_center)
            ellipse = tuple(ellipse)
            cv2.drawContours(gray, [contour], 0, (255, 0, 0), 1, offset=tuple(eye_roi[::-1, 0]))
            cv2.ellipse(gray, ellipse, (0, 0, 255), 2)
            epy, epx = np.round(eye_center).astype(int)
            gray[epx - 3:epx + 3, epy - 3:epy + 3] = 0
        cv2.imshow('frame', gray)

    def track(self, videofile, eye_roi, display=False):
        contrast_low = self._params['contrast_threshold']
        mask_kernel = np.ones((3, 3))
        dilation_iter = 10

        print("Tracking videofile", videofile)
        cap = cv2.VideoCapture(videofile)
        traces = []

        n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fr_count = 0
        if self._mask is not None:
            small_mask = self._mask[slice(*eye_roi[0]), slice(*eye_roi[1])].squeeze()
        else:
            small_mask = np.ones(np.diff(eye_roi, axis=1).squeeze().astype(int), dtype=np.uint8)

        while cap.isOpened():
            if fr_count >= n_frames:
                print("Reached end of videofile ", videofile)
                break

            # --- read frame
            ret, frame = cap.read()
            fr_count += 1

            # --- if we don't get a frame, don't add any tracking results
            if not ret:
                traces.append(dict(frame_id=fr_count))
                continue

            # --- print out if there's not display
            if fr_count % 500 == 0:
                print("\tframe ({}/{})".format(fr_count, n_frames))

            # --- preprocess and treshold images
            gray, small_gray, img_std, thres, blur = self.preprocess_image(frame, eye_roi)

            # --- if contrast is too low, skip it
            if img_std < contrast_low:
                traces.append(dict(frame_id=fr_count,
                                   frame_intensity=img_std))
                print('_', end="", flush=True)
                if display:
                    self.display(gray, blur, thres, eye_roi, fr_count, n_frames)
                continue

            # --- detect contours
            ellipse, eye_center, contour = None, None, None

            if self._last_ellipse is not None:
                mask = np.zeros(small_mask.shape, dtype=np.uint8)
                cv2.ellipse(mask, tuple(self._last_ellipse), (255), thickness=cv2.FILLED)
                # cv2.drawContours(mask, [self._last_contour], -1, (255), thickness=cv2.FILLED)
                mask = cv2.dilate(mask, mask_kernel, iterations=dilation_iter)
                thres *= mask
            thres *= small_mask

            _, contours, hierarchy1 = cv2.findContours(thres.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            contour, ellipse = self.get_pupil_from_contours(contours, blur, small_mask)

            self._last_ellipse = ellipse

            if contour is None:
                traces.append(dict(frame_id=fr_count, frame_intensity=img_std))
            else:
                eye_center = eye_roi[::-1, 0] + np.asarray(ellipse[0])
                self._center = np.asarray(ellipse[0]) / np.asarray(small_gray.shape[::-1])
                self._radius = max(ellipse[1])

                traces.append(dict(center=eye_center,
                                   major_r=np.max(ellipse[1]),
                                   rotated_rect=np.hstack(ellipse),
                                   contour=contour.astype(np.int16),
                                   frame_id=fr_count,
                                   frame_intensity=img_std
                                   ))
            if display:
                self.display(self._mask * gray if self._mask is not None else gray, blur, thres, eye_roi,
                             fr_count, n_frames, ellipse=ellipse,
                             eye_center=eye_center, contour=contour, ncontours=len(contours))
            if (cv2.waitKey(1) & 0xFF == ord('q')):
                raise PipelineException('Tracking aborted')

        cap.release()
        cv2.destroyAllWindows()

        return traces


def adjust_gamma(image, gamma=1.0):
    # build a lookup table mapping the pixel values [0, 255] to
    # their adjusted gamma values
    invGamma = 1.0 / gamma
    table = np.array([((i / 255.0) ** invGamma) * 255
                      for i in np.arange(0, 256)]).astype("uint8")

    # apply gamma correction using the lookup table
    return cv2.LUT(image, table)


class ManualTracker:
    main_window = "Main Window"
    roi_window = "ROI"
    thres_window = "Thresholded"
    progress_window = "Progress"
    graph_window = "Area"

    def __init__(self, videofile):
        self.reset()

        cv2.namedWindow(self.main_window)
        cv2.namedWindow(self.graph_window)
        cv2.createTrackbar("mask brush", self.main_window,
                           self.brush, 100,
                           self.set_brush)
        cv2.createTrackbar("Gaussian blur half width", self.main_window,
                           self.blur, 20,
                           self.set_blur)
        cv2.createTrackbar("exponent", self.main_window,
                           self.power, 15,
                           self.set_power)
        cv2.createTrackbar("erosion/dilation iterations", self.main_window,
                           self.dilation_iter, 30,
                           self.set_dilation)
        cv2.createTrackbar("min contour length", self.main_window,
                           self.min_contour_len, 50,
                           self.set_min_contour)
        self.videofile = videofile

        cv2.setMouseCallback(self.main_window, self.mouse_callback)
        cv2.setMouseCallback(self.graph_window, self.graph_mouse_callback)
        # cv2.setMouseCallback(self.progress_window, self.progress_mouse_callback)

        self.update_frame = True  # must be true to ensure correct starting conditions
        self.contours_detected = None
        self.area = None
        self._progress_len = 800
        self._progress_height = 100
        self._width = 800

        self.dilation_factor = 1.3

    def mouse_callback(self, event, x, y, flags, param):
        if self._scale_factor is not None:
            x, y = map(int, (i / self._scale_factor for i in (x, y)))
        if event == cv2.EVENT_MBUTTONDOWN:
            if self._mask is not None:
                cv2.circle(self._mask, (x, y), self.brush, (0, 0, 0), -1)
        elif event == cv2.EVENT_RBUTTONDOWN:
            if self._mask is not None:
                cv2.circle(self._mask, (x, y), self.brush, (255, 255, 255), -1)
        elif event == cv2.EVENT_LBUTTONDOWN:
            self.start = (x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            self.end = (x, y)
            x = np.vstack((self.start, self.end))
            tmp = np.hstack((x.min(axis=0), x.max(axis=0)))
            self.roi = np.asarray([[tmp[1], tmp[3]], [tmp[0], tmp[2]]], dtype=int) + 1
            print('Set ROI to', self.roi)

    def graph_mouse_callback(self, event, x, y, flags, param):
        t0, t1 = self.t0, self.t1
        dt = t1 - t0
        sanitize = lambda t: int(max(min(t, self._n_frames - 1), 0))
        if event == cv2.EVENT_MBUTTONDOWN:
            frame = sanitize(t0 + x / self._progress_len * dt)

            print('Jumping to frame', frame)
            self.goto_frame(frame)
        elif event == cv2.EVENT_LBUTTONDOWN:
            self.t0_tmp = sanitize(t0 + x / self._progress_len * dt)
        elif event == cv2.EVENT_LBUTTONUP:
            t1 = sanitize(t0 + x / self._progress_len * dt)
            if t1 < self.t0_tmp:
                self.t0, self.t1 = t1, self.t0_tmp
            elif self.t0_tmp == t1:
                self.t0, self.t1 = self.t0_tmp, self.t0_tmp + 1
            else:
                self.t0, self.t1 = self.t0_tmp, t1
        elif event == cv2.EVENT_RBUTTONDOWN:
            self.del_tmp = sanitize(t0 + x / self._progress_len * dt)
        elif event == cv2.EVENT_RBUTTONUP:
            t1 = sanitize(t0 + x / self._progress_len * dt)
            if t1 < self.del_tmp:
                t0, t1 = t1, self.del_tmp
            else:
                t0, t1 = self.del_tmp, t1
            self.contours_detected[t0:t1] = False
            self.contours[t0:t1] = None

    def reset(self):
        self.pause = False
        self.step = 50
        self._cap = None
        self._frame_number = None
        self._n_frames = None
        self._last_frame = None
        self._mask = None
        self.brush = 20
        self.jump_frame = 0

        self.start = None
        self.end = None
        self.roi = None

        self.t0 = 0
        self.t1 = None

        self.blur = 3
        self.power = 3

        self.dilation_iter = 7
        self.dilation_kernel = np.ones((3, 3))

        self.histogram_equalize = False

        self.min_contour_len = 10
        self.skip = False

        self.help = True
        self._scale_factor = None
        self.dsize = None

    def set_brush(self, brush):
        self.brush = brush

    def set_blur(self, blur):
        self.blur = blur

    def set_power(self, power):
        self.power = power

    def set_dilation(self, d):
        self.dilation_iter = d

    def set_min_contour(self, m):
        self.min_contour_len = max(m, 5)
        print('Setting min contour length to', self.min_contour_len)

    help_text = """
        KEYBOARD:
        
        q       : quits
        space   : (un)pause
        a       : reset area
        s       : toggle skip
        b       : jump back 10 frames
        n       : jump to next frame
        r       : delete roi
        d       : drop frame
        c       : delete mask
        f       : reset jump frame
        [0-9]   : enter number for jump frame
        j       : jump to jump frame
        e       : toggle histogram equalization
        h       : toggle help
        
        MOUSE:  
        drag                      : drag ROI
        middle click              : add to mask
        right click               : delete from mask 
        middle click in area      : jump to location 
        drag and drop in area     : zoom in 
        drag and drop in area     : drop frames
        """

    def process_key(self, key):
        if key == ord('q'):
            return False
        elif key == ord(' '):
            self.pause = not self.pause
            return True
        elif key == ord('s'):
            self.skip = not self.skip
            return True
        elif key == ord('a'):
            self.t0, self.t1 = 0, self._n_frames
            return True
        elif key == ord('b'):
            self.goto_frame(self._frame_number - self.step)
            return True
        elif key == ord('n'):
            self.goto_frame(self._frame_number + 1)
            return True
        elif key == ord('e'):
            self.histogram_equalize = not self.histogram_equalize
            return True
        elif key == ord('r'):
            self.start = None
            self.end = None
            self.roi = None
            return True
        elif key == ord('d'):
            self.contours_detected[self._frame_number] = False
            self.contours[self._frame_number] = None
            self.goto_frame(self._frame_number + 1)
        elif key == ord('c'):
            self._mask = np.ones_like(self._mask) * 255
        elif key == ord('f'):
            print('Resetting jump frame')
            self.jump_frame = 0
        elif 48 <= key < 58:
            self.jump_frame *= 10
            self.jump_frame += key - 48
            self.jump_frame = min(self._n_frames, self.jump_frame)
            print('Jump frame is', self.jump_frame)
        elif key == ord('j'):
            self.goto_frame(self.jump_frame)
        elif key == ord('h'):
            self.help = not self.help
            return True

        return True

    def display_frame_number(self, img):
        font = cv2.FONT_HERSHEY_SIMPLEX
        fs = .6
        cv2.putText(img, "[{fr_count:05d}/{frames:05d}]".format(fr_count=self._frame_number, frames=self._n_frames),
                    (10, 30), font, fs, (255, 144, 30), 2)
        if self.contours[self._frame_number] is not None:
            cv2.putText(img, "OK", (200, 30), font, fs, (0, 255, 0), 2)
        else:
            cv2.putText(img, "NOT OK", (200, 30), font, fs, (0, 0, 255), 2)
        cv2.putText(img, "Jump Frame {}".format(self.jump_frame), (300, 30), font, fs, (255, 144, 30), 2)
        if self.skip:
            cv2.putText(img, "Skip", (10, 70), font, fs, (0, 0, 255), 2)
        if self.help:
            y0, dy = 70, 20
            for i, line in enumerate(self.help_text.replace('\t', '    ').split('\n')):
                y = y0 + i * dy
                cv2.putText(img, line, (10, y), font, fs, (255, 144, 30), 2)

    def read_frame(self):
        if not self.pause or self.update_frame:
            if not self.update_frame:
                self._frame_number += 1

            self.update_frame = False
            ret, frame = self._cap.read()

            self._last_frame = ret, frame
            if self._mask is None:
                self._mask = np.ones_like(frame) * 255

            self._last_frame = ret, frame
            if ret and frame is not None:
                return ret, frame.copy()
            else:
                return ret, None
        else:
            ret, frame = self._last_frame
            return ret, frame.copy()

    def preprocess_image(self, frame):
        h = int(self.blur)

        if self.power > 1:
            frame = np.array(frame / 255) ** self.power * 255
            frame = frame.astype(np.uint8)

        if self.histogram_equalize:
            cv2.equalizeHist(frame, frame)

        blur = cv2.GaussianBlur(frame, (2 * h + 1, 2 * h + 1), 0)
        _, thres = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        mask = cv2.erode(thres, self.dilation_kernel, iterations=self.dilation_iter)
        mask = cv2.dilate(mask, self.dilation_kernel, iterations=int(self.dilation_factor * self.dilation_iter))
        return thres, blur, mask

    def find_contours(self, thres):
        _, contours, hierarchy = cv2.findContours(thres.copy(), cv2.RETR_TREE,
                                                  cv2.CHAIN_APPROX_SIMPLE)  # remove copy when cv2=3.2 is installed
        if len(contours) > 1:
            contours = [c for i, c in enumerate(contours) if hierarchy[0, i, 3] == -1]
        contours = [c + self.roi[::-1, 0][None, None, :] for c in contours if len(c) >= self.min_contour_len]
        contours = [cv2.convexHull(c) for c in contours]
        return contours

    def goto_frame(self, no):
        self._frame_number = min(max(no, 0), self._n_frames - 1)
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, self._frame_number)
        self.update_frame = True

    def plot_area(self):
        t0, t1 = self.t0, self.t1
        dt = t1 - t0
        idx = np.linspace(t0, t1, self._progress_len, endpoint=False).astype(int)
        height = self._progress_height
        graph = (self.contours_detected[idx].astype(np.float) * 255)[None, :, None]
        graph = np.tile(graph, (height, 1, 3)).astype(np.uint8)
        area = (height - self.area[idx] / (self.area[idx].max() + 1) * height).astype(int)
        detected = self.contours_detected[idx]
        for x, y1, y2, det1, det2 in zip(count(), area[:-1], area[1:], detected[:-1], detected[1:]):
            if det1 and det2:
                graph = cv2.line(graph, (x, y1), (x + 1, y2), (209, 133, 4), thickness=2)

        if t0 <= self._frame_number <= t1:
            x = int((self._frame_number - t0) / dt * self._progress_len)
            graph = cv2.line(graph, (x, 0), (x, height), (0, 255, 0), 2)
        cv2.imshow(self.graph_window, graph)

    def run(self):
        self._cap = cap = cv2.VideoCapture(self.videofile)

        self._n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._frame_number = 0
        self.update_frame = True  # ensure correct starting conditions
        self.contours_detected = np.zeros(self._n_frames, dtype=bool)
        self.contours = np.zeros(self._n_frames, dtype=object)
        self.area = np.zeros(self._n_frames)
        self.contours[:] = None
        self.t0 = 0
        self.t1 = self._n_frames

        while cap.isOpened():
            if self._frame_number >= self._n_frames - 1:
                print("Reached end of videofile ", self.videofile)
                break

            ret, frame = self.read_frame()

            if ret and not self.skip and self.start is not None and self.end is not None:
                cv2.rectangle(frame, self.start, self.end, (0, 255, 255), 2)
                small_gray = cv2.cvtColor(frame[slice(*self.roi[0]), slice(*self.roi[1]), :], cv2.COLOR_BGR2GRAY)

                try:
                    thres, small_gray, dilation_mask = self.preprocess_image(small_gray)
                except:
                    print('Problems with processing reversing to frame', self._frame_number - 10, 'Please redraw ROI')
                    self.goto_frame(self._frame_number - 10)
                    self.start = self.end = self.roi = None
                    self.pause = True
                else:
                    if self._mask is not None:
                        small_mask = self._mask[slice(*self.roi[0]), slice(*(self.roi[1] + 1)), 0]
                        cv2.bitwise_and(thres, small_mask, dst=thres)
                        cv2.bitwise_and(thres, dilation_mask, dst=thres)

                    contours = self.find_contours(thres)
                    cv2.drawContours(frame, contours, -1, (0, 255, 0), 3)
                    cv2.drawContours(small_gray, contours, -1, (127, 127, 127), 3, offset=tuple(-self.roi[::-1, 0]))
                    if len(contours) > 1:
                        self.pause = True
                    elif len(contours) == 1:
                        area = np.zeros_like(small_gray)
                        area = cv2.drawContours(area, contours, -1, (255), thickness=cv2.FILLED,
                                                offset=tuple(-self.roi[::-1, 0]))
                        self.area[self._frame_number] = (area > 0).sum()
                        self.contours_detected[self._frame_number] = True
                        self.contours[self._frame_number] = contours[0]

                    cv2.imshow(self.roi_window, small_gray)
                    cv2.imshow(self.thres_window, thres)


            # --- plotting
            self.display_frame_number(frame)
            cv2.bitwise_and(frame, self._mask, dst=frame)
            if self._scale_factor is None:
                self._scale_factor = self._width / frame.shape[1]
                self.dsize = tuple(int(self._scale_factor * s) for s in frame.shape[:2])[::-1]
            frame = cv2.resize(frame, self.dsize)
            cv2.imshow(self.main_window, frame)
            self.plot_area()
            if not self.process_key(cv2.waitKey(5) & 0xFF):
                break

        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    tracker = ManualTracker('video2.mp4')
    tracker.run()
