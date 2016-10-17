# from com.app.nlan.Logic.Engine import Engine
# from com.app.nlan.Logic.Map import Map
import os
import sys

from MyStuff import MyStuff

sys.path.append('./')

def start():
    # a_map = Map('central_corridor')
    # a_game = Engine(a_map)
    # a_game.play()
    stuff = MyStuff()
    stuff.execute()
    print sys.path
    # print os.environ['PYTHONPATH']
    # print os.environ


start()
