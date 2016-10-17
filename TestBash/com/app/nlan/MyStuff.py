import os
import zipfile
# import rarfile


class MyStuff(object):

    # def unrar(self, dpath, xpath):
    #         for rar in os.listdir(dpath):
    #             filepath = os.path.join(dpath, rar)
    #             if not os.path.isfile(filepath):
    #                 self.unrar(filepath, filepath)
    #                 continue
    #             for rar in os.listdir(dpath):
    #                 if rarfile.is_rarfile(filepath):
    #                     with rarfile.RarFile(filepath) as opened_rar:
    #                         for f in opened_rar.infolist():
    #                             print (f.filename, f.file_size)
    #                             opened_rar.extractall(xpath)

    def unzip(self, dpath, xpath):
            for zip in os.listdir(dpath):
                filepath = os.path.join(dpath, zip)
                if not os.path.isfile(filepath):
                    self.unzip(filepath, filepath)
                    continue
                for rar in os.listdir(dpath):
                    if zipfile.is_zipfile(filepath):
                        with zipfile.ZipFile(filepath) as opened_zip:
                            for f in opened_zip.infolist():
                                print (f.filename, f.file_size)
                                opened_zip.extractall(xpath)

    def execute(self):
        xpath = "/mnt/d/Vuze Downloads/Series"
        dpath = "/mnt/d/Vuze Downloads/Series"
        # self.unrar(dpath, xpath)
        self.unzip(dpath, xpath)


